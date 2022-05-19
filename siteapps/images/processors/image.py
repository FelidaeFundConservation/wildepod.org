from io import BytesIO
import logging

from django.conf import settings
import dropbox
from images.models import Annotator, Bot, BoundingBox, Category, Image
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from utils.storages import MediaRootGoogleCloudStorage

# Create a dropbox client
dbx = dropbox.Dropbox(
    app_key=settings.DROPBOX_API_KEY,
    app_secret=settings.DROPBOX_API_SECRET,
    oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
)

# Create a storage object instance
storage = MediaRootGoogleCloudStorage()

# Retry strategy for calling megadetector cloud function
md_retry_strategy = Retry(
    total=5,
    # Setting allowed methods to false will retry on all methods
    # https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html?highlight=retry#urllib3.util.Retry
    allowed_methods=False,
    status_forcelist=[400, 408, 429, 500, 502, 503, 504],
    # Since the cloud function is slow, backoff is set to a large value
    # 120 should give values of 1min, 2mins, 4mins, 8mins and 16mins
    backoff_factor=120,
)
adapter = HTTPAdapter(max_retries=md_retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)


# Function to save the thumbnails of the image
# This function is run for every valid image uploaded into dropbox
def add_thumbnail(image: Image):
    """Function to retrieve thumbnails from dropbox and save it into google buckets for serving

    Returns the full storage url
    """
    logging.info("Retrieving thumbnail from dropbox..")
    # TODO: Handle error or Rollback on failure
    # Get a 1024x1024 thumbnail from dropbox.
    # This resolution should also work well for most ML models trained on top of resnet etc.
    metadata, response = dbx.files_get_thumbnail_v2(
        dropbox.files.PathOrLink(tag="path", value=image.dropbox_file_path),
        format=dropbox.files.ThumbnailFormat("jpeg", None),
        size=dropbox.files.ThumbnailSize("w1024h768", None),
        mode=dropbox.files.ThumbnailMode("bestfit", None),
    )
    logging.info("Successfully retrieved thumbnail from dropbox.")

    # Convert image binary to bytestream
    img_bytes = BytesIO(response.content)
    logging.info("Successfully converted thumbnail binary to bytestream.")

    target_path = f"thumbnails/1024/{image.dropbox_content_hash}.jpg"
    gcloud_path = storage.save(target_path, img_bytes)
    logging.info("Successfully saved thumbnail to google cloud storage.")

    image.thumbnail_gcloud_path = gcloud_path
    # Save the image
    image.save()
    logging.info("Successfully saved image object to database.")


def add_bounding_boxes(image: Image):
    """Function to add bounding boxes to an image using MegaDetector's object detection model"""
    # TODO: Handle error or Rollback on failure
    # Run MegaDetector on each image and create the relevant annotation objects
    # TODO: Probably a better way to handle this. Hardcoded for now. Might not even need a model/record for this
    bot, created = Bot.objects.get_or_create(
        name="MegaDetector",
        version="4.1.0",
        task_type="Object Detection",
        model_api_url=settings.MEGADETECTOR_URL,
        model_file_url=f"gs://{settings.MODEL_STORAGE_BUCKET}/md_v4.1.0.pb",
    )
    if created:
        logging.info("Megadetector 4.1.0 object detection bot successfully created")
    else:
        logging.info("Megadetector 4.1.0 object detection bot already exists. Successfully retrieved.")

    annotator, created = Annotator.objects.get_or_create(type="bot", bot=bot)
    if created:
        logging.info("Megadetector annotator object successfully created")
    else:
        logging.info("Megadetector annotator object already exists. Successfully retrieved.")

    image_url = f"""gs://{settings.GS_BUCKET_NAME}/media/{image.thumbnail_gcloud_path}"""
    logging.info(f"Calling MegaDetector on image with url - {image_url}")
    # Call the MegaDetector cloud function
    # There is a really high timeout here since the cloud function takes a while to start on first request
    response = http.post(bot.model_api_url, json={"image": image_url, "model": bot.model_file_url}, timeout=300)
    if response.status_code == 200:
        result = response.json()
        logging.info(f"""MegaDetector cloud function call successful. {len(result["detections"])} objects detected""")
    else:
        logging.error(f"MegaDetector cloud function failed with status code: {response.status_code}")
        return
    # TODO: Investigate pros/cons of making these db operations an atomic transaction within django

    # For each detected bounding box, create a corresponding annotation object
    # Confidence for bounding box & category are the same for MegaDetector
    for i, detection in enumerate(result["detections"]):
        # Create a new annotation object
        bounding_box, created = BoundingBox.objects.get_or_create(
            image=image,
            confidence=detection["conf"],
            x=detection["bbox"][0],
            y=detection["bbox"][1],
            w=detection["bbox"][2],
            h=detection["bbox"][3],
            created_by=annotator,
        )
        if created:
            logging.info(
                f"""Successfully created bounding box for object #{i+1} - {detection["category"]} (confidence - {detection["conf"]})"""
            )
        else:
            logging.info("Bounding box already exists. Successfully retrieved.")
        # Next, create a category annotation for it
        category, _ = Category.objects.get_or_create(
            bounding_box=bounding_box,
            name=detection["category"],
            created_by=annotator,
            confidence=detection["conf"],
        )

    logging.info("All bounding boxes created successfully.")


# Function to process an image
def process_image(image: Image):
    """Function to process an image and create relevant metadata"""
    # First, add a thumbnail to the image object if it doesn't already exist
    if not image.thumbnail_gcloud_path:
        logging.info("Thumbnail for image doesn't exist. Adding..")
        add_thumbnail(image)
    else:
        logging.info("Thumbnail for image already exists. Skipping..")

    logging.info("Adding bounding boxes to image..")
    # Next, add bounding boxes to the image object
    add_bounding_boxes(image)
    logging.info("Finished adding bounding boxes to image..")

    image.processed = True
    image.save()
    logging.info("Successfully saved image to database.")

    # Additional Species detection annotations go here.
