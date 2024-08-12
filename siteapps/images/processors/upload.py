import concurrent.futures
import logging
import threading
import time
import uuid
from datetime import timedelta
from io import BytesIO

import dropbox
import requests
from django.conf import settings
from images.models import Image, Upload
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from .image import process_image

# Create a dropbox client
dbx = dropbox.Dropbox(
    app_key=settings.DROPBOX_APP_KEY,
    app_secret=settings.DROPBOX_APP_SECRET,
    oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
)
logging.getLogger("dropbox").setLevel(logging.WARNING)

# NOTE: Dropbox doesn't like this going too high.
# A workaround might be to get all file metadata separately with fewer threads
# and then hit cloud run with more threads.
# For now, this isn't critical since the processing is largely async
MAX_THREADS_FOR_IMAGE_PROCESSING = 10
MAX_THREADS_FOR_DROPBOX_API = 15


def clone_data_sheet(file, upload):
    """
    Uploads a copy of the data sheet to the upload folder in dropbox

    Arguments
    ---
        - file (InMemoryUploadedFile): The temporary file object created from submitting the upload form.
        - upload (images.models.Upload): The upload obj that was created to pull info from.
    """
    file_bytes = file.read()

    # This field doesn't exist until obj is saved, so need to calculate manually
    dropbox_folder_name = (
        f"{upload.date_retrieved.date()} - {upload.camera_station.micro_site.macro_site.name} -"
        f" {upload.camera_station.station_id}".lower()
    )

    path = f"/{dropbox_folder_name}/data_sheet/{upload.data_sheet.name}"

    response = dbx.files_upload(file_bytes, path)


def check_image_valid(image):
    image_file_path = f"{settings.MEDIA_URL}{image.thumbnail_gcloud_path}"
    response = requests.get(image_file_path)

    if response.status_code == 200:
        # Get the image data
        try:
            PILImage.open(BytesIO(response.content)).convert("RGB")
            return True
        except UnidentifiedImageError:
            logging.info(f"Couldn't open image {image_file_path}. Staged for deletion.")
            return False
    else:
        logging.info(f"Couldn't retrieve image {image_file_path} - {response.status_code} {response.reason}.")
        return None


def precompute_context_images(upload):
    # Precompute context images for each img in the upload
    CONTEXT_AMOUNT = 20

    upload_images = Image.objects.filter(upload=upload)

    for image in upload_images:
        if image.trigger_timestamp is not None:
            image.context_image_gcloud_paths = list(
                Image.objects.filter(
                    upload=image.upload,
                    upload__camera_station=image.upload.camera_station,
                    trigger_timestamp__lt=image.trigger_timestamp,
                    trigger_timestamp__gt=image.trigger_timestamp - timedelta(minutes=10),
                ).values_list("thumbnail_gcloud_path", flat=True)[:CONTEXT_AMOUNT]
            ) + list(
                Image.objects.filter(
                    upload=image.upload,
                    upload__camera_station=image.upload.camera_station,
                    trigger_timestamp__gte=image.trigger_timestamp,
                    trigger_timestamp__lt=image.trigger_timestamp + timedelta(minutes=10),
                ).values_list("thumbnail_gcloud_path", flat=True)[:CONTEXT_AMOUNT]
            )
            image.save()


def get_dropbox_file_listing(dropbox_folder_path: str) -> list:
    """Function to get a list of files in a dropbox directory."""

    logging.info("Retrieving file listing for the dropbox directory..")
    # NOTE: retry on error is already built into the dropbox client and is not required here
    # Next, get the list of all files in this directory and create relevant image objects
    response = dbx.files_list_folder(dropbox_folder_path, recursive=True)
    # Recursively gather all the entries
    entries = response.entries
    # TODO: The part where pagination happens is untested
    while response.has_more:
        response = dbx.files_list_folder_continue(response.cursor)
        entries += response.entries

    logging.info(f"Directory listing successful. A total of {len(entries)} entries were retrieved.")

    return entries


def preretrieve_file_metadata(entries, metadata_dict):
    preretrieved_metadata_lock = threading.Lock()

    def append_metadata(entry):
        data = dbx.files_get_metadata(entry.path_lower, include_media_info=True)

        with preretrieved_metadata_lock:
            metadata_dict[entry.path_lower] = data

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_FOR_DROPBOX_API) as executor:
        futures = [
            executor.submit(
                append_metadata,
                entry=entry,
            )
            for entry in entries
        ]


def get_metadata_with_retry(preretrieved_metadata, entry, max_retries=10, delay=10):
    retries = 0
    while retries < max_retries:
        try:
            response = preretrieved_metadata[entry.path_lower]
            return response
        except KeyError:
            retries += 1
            time.sleep(delay)
    return None


def process_dropbox_file(
    upload: Upload,
    entry: dropbox.files.FileMetadata,
    preretrieved_metadata: dict,
    files_to_delete: list,
    files_to_delete_lock: threading.Lock,
):
    """Process each file in the dropbox directory."""
    # By default, processed return True. This is to ensure that non-image files don't affect upload status
    processed = True

    # Process only files
    if isinstance(entry, dropbox.files.FileMetadata):
        # Retrieve their metadata along with media info
        response = get_metadata_with_retry(preretrieved_metadata, entry)

        # Check if the file's content matches another checked file
        # Don't create an object and stage the file for deletion if so
        if Image.objects.filter(dropbox_content_hash=response.content_hash).exists():
            with files_to_delete_lock:
                files_to_delete.append(dropbox.files.DeleteArg(path=entry.path_lower))
                logging.info(f"Duplicate file content found in file {response.name}. Staged for deletion.")

                return processed

        # Get media info
        media_info = response.media_info.get_metadata()

        # Next, only process image or video content
        if isinstance(media_info, (dropbox.files.PhotoMetadata, dropbox.files.VideoMetadata)):
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

                img_obj.save()

            # Once all the image objects are created, process them
            # This involves getting an image thumbnail and saving it to google cloud storage
            # followed by running ML to detect and identify objects in the image
            if not img_obj.processed and not img_obj.is_video:
                # NOTE: Without waiting for a return value, the thread will continue to run and skip the coroutine object
                # Also, processed state is updated only after the image has been processed
                processed = process_image(img_obj)

                # Remove corrupted images
                img_valid = check_image_valid(img_obj)
                if img_valid is False:
                    with files_to_delete_lock:
                        files_to_delete.append(dropbox.files.DeleteArg(path=entry.path_lower))
                        img_obj.delete()

                        return processed

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

    if upload.upload_method == "E":
        logging.info("Closing dropbox request..")
        # If not, first close the dropbox request & update the object status
        dbx.file_requests_update(id=upload.dropbox_request_id, open=False)
        upload.dropbox_request_open = False

    # Save the upload object
    upload.save()
    logging.info("Successfully closed dropbox request.")

    # Get the list of file entries in the dropbox directory
    entries = get_dropbox_file_listing(upload.dropbox_folder_path)

    # Save the item count in a global dict
    dropbox_item_counts[f"{upload_id}"] = len(entries)

    # Process each dropbox entry inside a thread. Throttle the number of threads as needed
    # NOTE: This is a thread safe operation since image objects are independent functions over a dropbox entry & the upload
    # Even in case of multiple threads processing the same upload, at the very worst, it'll result in re-processing the
    # same image object. Bounding box detection will be done again but won't be stored as long as there is no variation
    # in the output of MegaDetector (which is likely)

    # This multithreaded operation is run inside a thread pool instead of manual thread creation
    processed_status = []

    # Store content hashes shared between threads to check duplicates.
    files_to_delete = []
    files_to_delete_lock = threading.Lock()

    # Skip checking already-processed entries
    processed_list = upload.images.filter(processed=True).values_list("dropbox_file_path", flat=True)
    logging.info(f"{len(entries)} entries found. Skipping processed entries...")

    entries = [entry for entry in entries if entry.path_lower not in processed_list]
    logging.info(f"Processing remaining {len(entries)} entries.")

    # Pre-retrieve metadata for all files asynchronously
    preretrieved_metadata = {}

    metadata_thread = threading.Thread(target=preretrieve_file_metadata, args=(entries, preretrieved_metadata))
    metadata_thread.start()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_FOR_IMAGE_PROCESSING) as executor:
        # Process each entry in the dropbox directory
        futures = [
            executor.submit(
                process_dropbox_file,
                upload=upload,
                entry=entry,
                preretrieved_metadata=preretrieved_metadata,
                files_to_delete=files_to_delete,
                files_to_delete_lock=files_to_delete_lock,
            )
            for entry in entries
        ]

        for i, processed in enumerate(concurrent.futures.as_completed(futures)):
            try:
                processed = processed.result()
                processed_status.append(processed)

                if i % 200 == 0:
                    logging.info(f"Processed {i+1}/{len(entries)} entries.")
            except Exception as e:
                logging.error(f"Error processing entry {i+1}/{len(entries)} - {e}")
                continue

    # Delete files with duplicate content from dropbox directory
    if len(files_to_delete) > 0:
        # Split list into <1000 object chunks
        def chunk_list(lst, chunk_size):
            for i in range(0, len(lst), chunk_size):
                yield lst[i : i + chunk_size]

        chunks = list(chunk_list(files_to_delete, 1000))

        # Make Dropbox API calls
        logging.info("Attempting to delete duplicate files...")

        def poll_delete_job(delete_job_id):
            is_complete = False
            is_failed = False
            attempts = 0

            # Keep checking status until deletion job finishes or fails.
            while not is_complete and not is_failed and attempts < 20:
                delete_job_status = dbx.files_delete_batch_check(delete_job_id)
                is_complete = delete_job_status.is_complete()
                is_failed = delete_job_status.is_failed()

                if is_complete:
                    logging.info("Duplicate image batch successfully deleted from Dropbox.")
                    break
                elif is_failed:
                    logging.error(
                        f"Error deleting files with duplicate content from dropbox directory: {delete_job_status.get_failed()}"
                    )
                    break
                else:
                    pass

                time.sleep(3)
                attempts += 1

        # Make calls to delete each chunk
        for chunk in chunks:
            delete_job_id = dbx.files_delete_batch(chunk).get_async_job_id()
            thread = threading.Thread(target=poll_delete_job, args=(delete_job_id))
            thread.start()

        logging.info(
            f"{len(files_to_delete)} of {len(entries)} file(s) were found to have duplicate content, and will be deleted from the Dropbox directory.\n"
            f"The {len(entries) - len(files_to_delete)} remaining file(s) will be unique."
        )
    else:
        logging.info("No duplicate files to delete found.")

    # Only if all files are successfully processed, mark the upload as processed
    if all(processed_status):
        precompute_context_images(upload)
        # NOTE: Processed is set to True for non-image files by default since they don't require any processing
        # Deleted duplicate files also return True
        logging.info("All images processed. Marking upload as processed..")
        # Mark the upload as processed.
        upload.processed = True
        # Save the upload object
        upload.save()
        logging.info("Upload saved successfully.")
    else:
        logging.error("Processing failed for one or more images. Upload not marked as processed.")

    # Remove the item count from dict when processing complete
    dropbox_item_counts.pop(upload_id, None)


# For uploads still processing,
# save total item count to accurately show progress in upload list.
dropbox_item_counts = {}


def get_dropbox_item_count(upload_id: str):
    return dropbox_item_counts.get(upload_id, "?")
