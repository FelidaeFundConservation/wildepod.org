import concurrent.futures
import logging
import threading
import time
import uuid

import dropbox
from django.conf import settings
from images.models import Image, Upload

from .image import process_image

# Create a dropbox client
dbx = dropbox.Dropbox(
    app_key=settings.DROPBOX_APP_KEY,
    app_secret=settings.DROPBOX_APP_SECRET,
    oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
)

MAX_THREADS_FOR_IMAGE_PROCESSING = 25


def get_dropbox_file_listing(dropbox_folder_path: str) -> list:
    """Function to get a list of files in a dropbox directory."""

    logging.info("Retrieving file listing for the dropbox directory..")
    # NOTE: retry on error is already built into the dropbox client and is not required here
    # Next, get the list of all files in this directory and create relevant image objects
    response = dbx.files_list_folder(dropbox_folder_path, recursive=True)
    # Recursively gather all the entries
    entries = response.entries
    logging.info(f"Retrieved {len(response.entries)} entries..")
    # TODO: The part where pagination happens is untested
    while response.has_more:
        logging.info("There are more entries remaining! Retrieving next set..")
        response = dbx.files_list_folder_continue(response.cursor)
        entries += response.entries
        logging.info(f"Retrieved {len(response.entries)} entries..")
        logging.info(f"Total entries now at {len(entries)}.")

    logging.info(f"Directory listing successful. A total of {len(entries)} entries were retrieved.")

    return entries


def process_dropbox_file(upload: Upload, entry: dropbox.files.FileMetadata):
    """Process each file in the dropbox directory."""
    logging.info(
        f"Processing metadata for entry - '{entry.path_lower}' inside thread with id - '{threading.get_ident()}' & name - '{threading.current_thread().name}'"
    )

    # By default, processed return True. This is to ensure that non-image files don't affect upload status
    processed = True

    # Process only files
    if isinstance(entry, dropbox.files.FileMetadata):
        # Retrieve their metadata along with media info
        # "include_media_info" is deprecated in the files_list_folder API requiring a call for each file again
        # TODO: Maybe this can be offloaded to an on-demand functionality that retrieves data only if needed
        response = dbx.files_get_metadata(entry.path_lower, include_media_info=True)
        media_info = response.media_info.get_metadata()
        logging.info(f"Retrieved media info for entry - '{entry.path_lower}'")

        # Next, only process image or video content
        if isinstance(media_info, (dropbox.files.PhotoMetadata, dropbox.files.VideoMetadata)):
            logging.info("Entry is an image or video. Processing..")
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
            if created:
                logging.info(f"Image object for entry '{entry.path_lower}' created. Adding metadata..")

                # Update other fields along with custom data extracted if they exist
                if media_info.time_taken:
                    img_obj.trigger_timestamp = media_info.time_taken
                if media_info.dimensions:
                    img_obj.height = media_info.dimensions.height
                    img_obj.width = media_info.dimensions.width
                if media_info.location:
                    img_obj.latitude = media_info.location.latitude
                    img_obj.longitude = media_info.location.longitude
                if img_obj.is_video and media_info.duration:
                    img_obj.duration = media_info.duration

                logging.info("Image object's metadata added. Saving..")
                img_obj.save()
                logging.info("Image object saved successfully.")
            else:
                logging.info(f"Image object for entry '{entry.path_lower}' already exists. Object retrieved!")

            # Once all the image objects are created, process them
            # This involves getting an image thumbnail and saving it to google cloud storage
            # followed by running ML to detect and identify objects in the image
            logging.info(f"Processing image object '{img_obj.id}' ({img_obj.dropbox_file_name})..")
            if not img_obj.processed and not img_obj.is_video:
                # NOTE: Without waiting for a return value, the thread will continue to run and skip the coroutine object
                # Also, processed state is updated only after the image has been processed
                processed = process_image(img_obj)
            else:
                logging.info("Image already processed or is a video. Skipping..")

    # Processed is set to False if the file is a valid image & the processing failed
    return processed


# Function to process an upload
# This is triggered inside a separate thread to asynchronously process the upload
# The processing includes getting a directory listing using dropbox API and creating
# & processing image objects retrieved.
def process_upload(upload_id: uuid.UUID):
    """Function to process a dropbox upload.
    This function creates image objects corresponding to the files in the dropbox directory
    """
    # This thread can start before the model save is completed on update
    # To ensure the latest copy of the object is retrieved here, the function
    # will wait until the "upload_complete" flag is set in the retrieved object
    # TODO: This is a hacky piece of code. Might need a cleaner implementation here
    num_retries = 5
    seconds_between_attempts = 2
    logging.info(f"Thread initiated. Waiting for upload '{upload_id}' to be committed to database..")
    for _ in range(num_retries):
        # Get the upload object
        upload = Upload.objects.get(pk=upload_id)
        # Break out of the loop if upload_complete flag is set
        if upload.upload_complete:
            break
        # Else wait for the specified number of seconds
        else:
            time.sleep(seconds_between_attempts)

    logging.info(
        f"Starting processing of upload '{upload.id}' from camera station '{upload.camera_station}' retreived on {upload.date_retrieved}"
    )

    # Skip processing if the upload is already processed
    if upload.processed:
        logging.info(f"Upload '{upload.id}' already processed. Skipping processing..")
        return

    logging.info("Closing dropbox request..")
    # If not, first close the dropbox request & update the object status
    dbx.file_requests_update(id=upload.dropbox_request_id, open=False)
    upload.dropbox_request_open = False
    # Save the upload object
    upload.save()
    logging.info("Successfully closed dropbox request.")

    # Get the list of file entries in the dropbox directory
    entries = get_dropbox_file_listing(upload.dropbox_folder_path)

    # Process each dropbox entry inside a thread. Throttle the number of threads as needed
    # NOTE: This is a thread safe operation since image objects are independent functions over a dropbox entry & the upload
    # Even in case of multiple threads processing the same upload, at the very worst, it'll result in re-processing the
    # same image object. Bounding box detection will be done again but won't be stored as long as there is no variation
    # in the output of MegaDetector (which is likely)

    # This multithreaded operation is run inside a thread pool instead of manual thread creation
    processed_status = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_FOR_IMAGE_PROCESSING) as executor:
        # Process each entry in the dropbox directory
        futures = [executor.submit(process_dropbox_file, upload, entry) for entry in entries]
        for i, processed in enumerate(concurrent.futures.as_completed(futures)):
            try:
                processed = processed.result()
                logging.info(f"Processed {i+1}/{len(entries)} entries.")
                processed_status.append(processed)
            except Exception as e:
                logging.error(f"Error processing entry {i+1}/{len(entries)} - {e}")
                continue

    # Only if all files are successfully processed, mark the upload as processed
    if all(processed_status):
        # NOTE: Processed is set to True for non-image files by default since they don't require any processing
        logging.info("All images processed. Marking upload as processed..")
        # Mark the upload as processed.
        upload.processed = True
        # Save the upload object
        upload.save()
        logging.info("Upload saved successfully.")
    else:
        logging.error("Processing failed for one or more images. Upload not marked as processed.")
