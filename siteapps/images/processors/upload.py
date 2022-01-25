import logging
import time

import dropbox
from django.conf import settings
from images.models import Image, Upload

from .image import process_image

# Setup a logger
logger = logging.getLogger(__name__)

# Create a dropbox client
dbx = dropbox.Dropbox(settings.DROPBOX_AUTH_TOKEN)


# Function to process an upload
# This is triggered inside a separate thread to asynchronously process the upload
# The processing includes getting a directory listing using dropbox API and creating
# & processing image objects retrieved.
# TODO: For now, this is all done in a single function. Might need to split upload &
# image processing later
# TODO: Handle error or Rollback on failure
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
