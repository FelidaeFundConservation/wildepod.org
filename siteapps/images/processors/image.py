import logging
import time
from io import BytesIO

import dropbox
import requests
from django.conf import settings
from images.models import Annotator, Bot, BoundingBox, Category, Image

from config.settings.custom_storages import MediaStorage

# Setup a logger
logger = logging.getLogger(__name__)

# Create a dropbox client
dbx = dropbox.Dropbox(settings.DROPBOX_AUTH_TOKEN)

# Create a storage object instance
storage = MediaStorage()


# Function to save the thumbnails of the image
# This function is run for every valid image uploaded into dropbox
def add_thumbnail(image: Image):
    """Function to retrieve thumbnails from dropbox and save it into google buckets for serving

    Returns the full storage url
    """
    # TODO: Handle error or Rollback on failure
    # Get a 1024x1024 thumbnail from dropbox.
    # This resolution should also work well for most ML models trained on top of resnet etc.
    metadata, response = dbx.files_get_thumbnail_v2(
        dropbox.files.PathOrLink(tag="path", value=image.dropbox_file_path),
        format=dropbox.files.ThumbnailFormat("jpeg", None),
        size=dropbox.files.ThumbnailSize("w1024h768", None),
        mode=dropbox.files.ThumbnailMode("bestfit", None),
    )

    # Convert image binary to bytestream
    img_bytes = BytesIO(response.content)
    target_path = f"compressed/1024/{image.dropbox_content_hash}.jpg"
    gcloud_path = storage.save(target_path, img_bytes)

    image.thumbnail_gcloud_path = gcloud_path


# Function to process an image
def process_image(image: Image):
    """Function to process an image and create relevant metadata"""
    # First, add a thumbnail to the image object
    add_thumbnail(image)
    # TODO: Handle error or Rollback on failure
    # Next, run MegaDetector on each image and create the relevant annotation objects
    image_url = f"""gs://{settings.GS_MEDIA_STORAGE_BUCKET_NAME}/{image.thumbnail_gcloud_path}"""
    # TODO: Probably a better way to handle this. Hardcoded for now. Might not even need a model/record for this
    bot, _ = Bot.objects.get_or_create(
        name="MegaDetector",
        version="4.1.0",
        task_type="Object Detection",
        model_api_url=settings.MEGADETECTOR_URL,
        model_file_url=f"gs://{settings.MODEL_STORAGE_BUCKET}/md_v4.1.0.pb",
    )
    annotator, _ = Annotator.objects.get_or_create(type="bot", bot=bot)
    # Call the MegaDetector cloud function
    result = requests.post(bot.model_api_url, json={"image": image_url, "model": bot.model_file_url}).json()
    # TODO: Handle errors

    # For each detected bounding box, create a corresponding annotation object
    # Confidence for bounding box & category are the same for MegaDetector
    for detection in result["detections"]:
        # Create a new annotation object
        bounding_box = BoundingBox.objects.create(
            image=image,
            confidence=detection["conf"],
            x=detection["bbox"][0],
            y=detection["bbox"][1],
            w=detection["bbox"][2],
            h=detection["bbox"][3],
            created_by=annotator,
        )
        # Next, create a category annotation for it
        _ = Category.objects.create(
            bounding_box=bounding_box,
            name=detection["category"],
            created_by=annotator,
            confidence=detection["conf"],
        )

    # TODO: Additional Species detection annotations go here.
    # Add annotation type automatically linked to each annotation perhaps?
