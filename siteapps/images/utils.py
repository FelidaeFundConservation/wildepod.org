import logging
import time
from io import BytesIO

import dropbox
import requests
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from config.settings.custom_storages import MediaStorage

from .models import Annotator, Bot, BoundingBox, Category, Image, Upload

# Setup a logger
logger = logging.getLogger(__name__)

# Create a dropbox client
dbx = dropbox.Dropbox(settings.DROPBOX_AUTH_TOKEN)

# Create a storage object instance
storage = MediaStorage()


def flatten_annotorious_annotations(annotations: list):
    """Function to take an annotorious formatted list and flatten it with numerical bounding boxes"""
    formatted_annotations = {}
    for annotation in annotations:
        # Annotorious created ids add a # in front of the annotation id. Remove it
        clean_uuid = annotation["id"].replace("#", "")

        # Get the x,y,w,h values from the annotation
        # Annotorious values are in percent so divide by 100 to conform with Mega Detectors values
        [x, y, w, h] = annotation["target"]["selector"]["value"].split(":")[1].split(",")
        [x, y, w, h] = list(map(lambda x: round(float(x), 6) / 100, [x, y, w, h]))

        # Append the annotation to the list
        formatted_annotations[clean_uuid] = {
            "id": clean_uuid,
            "category": annotation["body"][0]["value"],
            "confidence": annotation["body"][0]["confidence"],
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }

    return formatted_annotations


# Function to process a list of annotations for MegaDetector's Object Detection model
# Annotations follow the Annotorious format
def process_md_annotations(image_id: str, annotations: list, annotator: Annotator, initial_bboxes: list):
    """Function to process a list of annotations for MegaDetector's Object Detection model

    Annotations follow the Annotorious format
    """
    # Format the annotorious annotations
    formatted_annotations = flatten_annotorious_annotations(annotations)
    # Convert initial boxes into the same structure
    initial_bboxes = {bbox["id"]: bbox for bbox in initial_bboxes}

    # First handle all deletions
    for bbox_id in initial_bboxes:
        # If the annotation is not in the list of annotations, it is a rejection
        if bbox_id not in formatted_annotations:
            print(f"Deleting {bbox_id}")
            # First get the bounding box
            bbox_obj = BoundingBox.objects.get(id=bbox_id)
            # Add the annotator to its rejection list
            bbox_obj.accepted_by.remove(annotator)
            bbox_obj.rejected_by.add(annotator)
            bbox_obj.save()

    # Next, handles all additions
    for bbox_id in formatted_annotations:
        # If the annotation is not in the initial list, it is a new annotation
        if bbox_id not in initial_bboxes:
            # Create a new bounding box
            bbox_obj = BoundingBox(
                image=Image.objects.get(id=image_id),
                x=formatted_annotations[bbox_id]["x"],
                y=formatted_annotations[bbox_id]["y"],
                w=formatted_annotations[bbox_id]["w"],
                h=formatted_annotations[bbox_id]["h"],
                category=formatted_annotations[bbox_id]["category"],
                confidence=formatted_annotations[bbox_id]["confidence"],
                created_by=annotator,
            )
            bbox_obj, _ = BoundingBox.objects.get_or_create(
                image=Image.objects.get(id=image_id),
                x=formatted_annotations[bbox_id]["x"],
                y=formatted_annotations[bbox_id]["y"],
                w=formatted_annotations[bbox_id]["w"],
                h=formatted_annotations[bbox_id]["h"],
                confidence=formatted_annotations[bbox_id]["confidence"],
                created_by=annotator,
            )
            # Next, create a category annotation for it
            category_obj, _ = Category.objects.get_or_create(
                bounding_box=bbox_obj,
                name=formatted_annotations[bbox_id]["category"],
                created_by=annotator,
                confidence=formatted_annotations[bbox_id]["confidence"],
            )
            bbox_obj.save()

    # Finally handle updates. This includes accept/reject depending on the category labels provided
    for bbox_id in initial_bboxes:
        if bbox_id in formatted_annotations:
            # Get the bounding box object
            bbox_obj = BoundingBox.objects.get(id=bbox_id)
            bbox_obj.rejected_by.remove(annotator)
            bbox_obj.accepted_by.add(annotator)

            # If the class label is the same, its an accept. Else, its a rejection + a new label addition/accept if it exists
            if initial_bboxes[bbox_id]["category"] == formatted_annotations[bbox_id]["category"]:
                category_obj = Category.objects.get(bounding_box=bbox_obj, name=initial_bboxes[bbox_id]["category"])
                category_obj.rejected_by.remove(annotator)
                category_obj.accepted_by.add(annotator)
                category_obj.save()
            else:
                category_obj = Category.objects.get(bounding_box=bbox_obj, name=initial_bboxes[bbox_id]["category"])
                category_obj.accepted_by.remove(annotator)
                category_obj.rejected_by.add(annotator)
                category_obj.save()

                # Create a new category if it doesn't exist
                try:
                    new_category_obj = Category.objects.get(
                        bounding_box=bbox_obj, name=formatted_annotations[bbox_id]["category"]
                    )
                    new_category_obj.rejected_by.remove(annotator)
                    new_category_obj.accepted_by.add(annotator)
                    new_category_obj.save()

                except ObjectDoesNotExist:
                    new_category_obj = Category.objects.create(
                        bounding_box=bbox_obj,
                        name=formatted_annotations[bbox_id]["category"],
                        created_by=annotator,
                        confidence=formatted_annotations[bbox_id]["confidence"],
                    )

            bbox_obj.save()


# Function to save the thumbnails of the image
# This function is run for every valid image uploaded into dropbox
def add_thumbnail(image: Image):
    """Function to retrieve thumbnails from dropbox and save it into google buckets for serving

    Returns the full storage url
    """
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
    gcloud_url = storage.save(target_path, img_bytes)

    image.thumbnail_url = gcloud_url


# Function to process an image
def process_image(image: Image):
    """Function to process an image and create relevant metadata"""
    print("STARTING STUFF")
    # First, add a thumbnail to the image object
    add_thumbnail(image)
    print("THUMBNAIL ADDED")

    # Next, run MegaDetector on each image and create the relevant annotation objects
    image_url = f"""gs://{settings.GS_MEDIA_STORAGE_BUCKET_NAME}/{image.thumbnail_url}"""
    # TODO: Probably a better way to handle this. Hardcoded for now. Might not even need a model/record for this
    bot, _ = Bot.objects.get_or_create(
        name="MegaDetector",
        version="4.1.0",
        task_type="Object Detection",
        model_api_url="http://us-west2-zara-82380.cloudfunctions.net/megadetector_open",
        model_file_url="gs://feldae_models/md_v4.1.0.pb",
    )
    annotator, _ = Annotator.objects.get_or_create(type="bot", bot=bot)
    # Call the MegaDetector cloud function
    result = requests.post(bot.model_api_url, json={"image": image_url, "model": bot.model_file_url}).json()
    # TODO: Handle errors
    print(result)

    # For each detected bounding box, create a corresponding annotation object
    # Confidence for bounding box & category are the same for MegaDetector
    for detection in result["detections"]:
        # Create a new annotation object
        bounding_box, _ = BoundingBox.objects.get_or_create(
            image=image,
            confidence=detection["conf"],
            x=detection["bbox"][0],
            y=detection["bbox"][1],
            w=detection["bbox"][2],
            h=detection["bbox"][3],
            created_by=annotator,
        )
        # Next, create a category annotation for it
        category, _ = Category.objects.get_or_create(
            bounding_box=bounding_box,
            name=detection["category"],
            created_by=annotator,
            confidence=detection["conf"],
        )

    # TODO: Additional Species detection annotations go here.
    # Add annotation type automatically linked to each annotation perhaps?


# Function to process an upload
# This is triggered inside a separate thread to asynchronously process the upload
# The processing includes getting a directory listing using dropbox API and creating
# & processing image objects retrieved.
# TODO: For now, this is all done in a single function. Might need to split upload &
# image processing later
def process_upload(upload_id: int):
    """Function to process a dropbox upload.
    This function creates image objects corresponding to the files in the dropbox directory
    """
    # This thread can start before the model save is completed on update
    # To ensure the latest copy of the object is retrieved here, the function
    # will wait until the "upload_complete" flag is set in the retrieved object
    # TODO: This is a hacky piece of code. Might need a cleaner implementation here
    total_attempts = 5
    seconds_between_attempts = 2

    for _ in range(total_attempts):
        # Get the upload object
        upload = Upload.objects.get(pk=upload_id)
        # Break out of the loop if upload_complete flag is set
        if upload.upload_complete:
            break
        # Else wait for the specified number of seconds
        else:
            time.sleep(seconds_between_attempts)

    logger.info(
        f"Thread initiated to process upload with id - {upload.id} from {upload.camera_station} retrieved on"
        f" {upload.date_retrieved}"
    )

    # First close the dropbox request
    dbx.file_requests_update(id=upload.dropbox_request_id, open=False)
    # Update the object status
    upload.dropbox_request_open = False

    # Next, get the list of all files in this directory and create relevant image objects
    response = dbx.files_list_folder(upload.dropbox_folder_path, recursive=True)
    # Recursively gather all the entries
    entries = response.entries
    # TODO: The part where pagination happens is untested
    while response.has_more:
        response = dbx.files_list_folder_continue(response.cursor)
        entries += response.entries

    # Process each entry & create relevant image/video objects
    for entry in entries:
        # Skip all folders
        if isinstance(entry, dropbox.files.FileMetadata):
            # Retrieve their metadata along with media info
            # "include_media_info" is deprecated in the files_list_folder API requiring a call for each file again
            # TODO: Maybe this can be offloaded to an on-demand functionality that retrieves data only if needed
            response = dbx.files_get_metadata(entry.path_lower, include_media_info=True)
            media_info = response.media_info.get_metadata()
            # Only process image or video content
            if isinstance(media_info, dropbox.files.PhotoMetadata) or isinstance(
                media_info, dropbox.files.VideoMetadata
            ):
                img_obj, created = Image.objects.get_or_create(
                    upload=upload,
                    dropbox_file_name=response.name,
                    dropbox_file_path=response.path_lower,
                    dropbox_file_path_display=response.path_display,
                    dropbox_content_hash=response.content_hash,
                    dropbox_file_id=response.id,
                    file_size=response.size,
                    is_video=isinstance(media_info, dropbox.files.VideoMetadata),
                )

                # Update other fields along with custom data extracted if they exist
                if media_info.time_taken:
                    img_obj.time_taken = media_info.time_taken
                if media_info.dimensions:
                    img_obj.height = media_info.dimensions.height
                    img_obj.width = media_info.dimensions.width
                if media_info.location:
                    img_obj.latitude = media_info.location.latitude
                    img_obj.longitude = media_info.location.longitude
                if img_obj.is_video and media_info.duration:
                    img_obj.duration = media_info.duration

                # Process the image.
                # This involves getting an image thumbnail and saving it to google cloud storage
                # followed by running ML to detect and identify objects in the image
                if not img_obj.is_video:
                    process_image(img_obj)

                img_obj.processed = True

                img_obj.save()

    # Mark the upload as processed.
    upload.processed = True

    # Save the upload object
    upload.save()
