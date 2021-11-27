import dropbox
from django.conf import settings
from django.db import models
from locations.models import CameraStation
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

# Create a dropbox client
dbx = dropbox.Dropbox(settings.DROPBOX_AUTH_TOKEN)


# Model for error types & its effects
class UploadError(TimeStampedModel):
    error = models.CharField("Error type", max_length=100, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.error

    class Meta:
        ordering = ("-created",)


class UploadErrorEffect(TimeStampedModel):
    error_effect = models.TextField("Error's effect", unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.error_effect

    class Meta:
        ordering = ("-created",)


class CameraStationAction(TimeStampedModel):
    action = models.TextField("Last action taken", unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.action

    class Meta:
        ordering = ("-created",)


# Model to log upload events.
class Upload(TimeStampedModel):
    # Camera station the uploads are linked to
    camera_station = models.ForeignKey(CameraStation, on_delete=models.PROTECT)

    # Date the SD card was retrieved
    date_retrieved = models.DateField()

    # Last action on the camera station
    last_action = models.ForeignKey(CameraStationAction, on_delete=models.PROTECT)

    # Uploader
    volunteer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    # Errors & effects
    error = models.ForeignKey(UploadError, blank=True, null=True, on_delete=models.PROTECT)
    error_effect = models.ForeignKey(UploadErrorEffect, blank=True, null=True, on_delete=models.PROTECT)

    # Any uploader comments associated with the SD card
    comments = models.TextField(blank=True, null=True)

    # Auto generated dropbox links
    # Folder name used for this upload in dropbox. This must be unique
    # Currently this is also auto generated which makes it impossible to create two uploads for a given station & a date
    # If this needs to be flexible, there needs to be some changes in how the name is generated
    dropbox_folder_name = models.TextField(unique=True)
    # The full path of the file. Everything is expected to be in the root of the app folder but this exists in case the folder structure changes
    dropbox_folder_path = models.TextField(unique=True)
    # Folder requests are automatically created with every upload. This is the id returned by dropbox. It'll always be unique
    dropbox_request_id = models.CharField(max_length=50)
    # This is a function of the request id with a url prefix
    dropbox_request_url = models.URLField()
    # Request state starts off as true and later, when marked as complete, will be marked as false (after updating dropbox state as well)
    dropbox_request_open = models.BooleanField(default=True)
    # Dropbox folder id. This is the id for the folder that was created along with the request. Unpopulated on init and might be populated later
    dropbox_folder_id = models.CharField(max_length=50, blank=True, null=True)
    # Share url for the folder. Folders, by default, will not be shared and will be empty unless explicitly shared
    dropbox_share_url = models.URLField(blank=True, null=True)

    # Upload status. This defaults to false. After dropbox upload has been completed, this should be set to true by the uploader
    upload_complete = models.BooleanField("Upload to Dropbox complete?", default=False)

    # History of model instance changes
    history = HistoricalRecords()

    # TODO: Create a model manager to generate a semantic name from
    # the camera station ID, the microsite name & the date retrieved
    # to have a semantic folder structure

    def save(self, *args, **kwargs):
        # If the object is being created for the first time, create a Dropbox request url and populate relevant fields
        if not self.id:
            # First auto-generate a foldername. Always lowercase since dropbox is case insensitive anyway
            self.dropbox_folder_name = (
                f"{self.date_retrieved} - {self.camera_station.micro_site.macro_site.name} -"
                f" {self.camera_station.station_id}".lower()
            )
            self.dropbox_folder_path = f"/{self.dropbox_folder_name}"
            # Now create a folder request. The path will always be relative to the app root.
            # The entire directory structure, for now, will be flat under the App directory
            response = dbx.file_requests_create(title=self.dropbox_folder_name, destination=self.dropbox_folder_path)
            # The response is a FileRequest object. Error handling/exceptions will be handled by the python package
            self.dropbox_request_id = response.id
            self.dropbox_request_url = response.url
            self.dropbox_request_open = response.is_open

        # When the upload is marked as complete, close the request and trigger a cloud task to process all the images
        # Initially this would be just listing the objects & saving their metadata.
        # Later, this will likely include image thumbnail creation for faster rendering and running ML to get tags
        if self.upload_complete:
            # First close the request
            dbx.file_requests_update(id=self.dropbox_request_id, open=False)

            # Next, get the list of all files in this directory and create relevant image objects
            # All the code starting here should be moved into an asynchronous task
            response = dbx.files_list_folder(self.dropbox_folder_path, recursive=True)
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
                            upload=self,
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

                        img_obj.save()

        super(Upload, self).save(*args, **kwargs)

    def __str__(self):
        return self.dropbox_folder_name

    class Meta:
        ordering = ("-created",)
        unique_together = [["camera_station", "date_retrieved"]]


# Each processed Image from an upload
# This is auto-created in the background after an upload to Google Drive has been finalized
# It is auto-updated later in the stream
class Image(TimeStampedModel):
    # Specific camera station upload the images are linked to
    upload = models.ForeignKey(Upload, on_delete=models.PROTECT)
    # Dropbox filename.
    # NOTE: Dropbox requests prepend files with the "Uploader's name" which should be removed to get the actual filename although not useful
    dropbox_file_name = models.TextField()
    # The full path of the file. This is especially required if the upload has a directory structure
    dropbox_file_path = models.TextField()
    # The display path. This is the actual file name with original casing (Dropbox is case insensitive)
    dropbox_file_path_display = models.TextField()
    # Dropbox's 64 character content hash. This can be used for deduplication and offsets the need to compute a local content hash
    # https://www.dropbox.com/developers/reference/content-hash
    dropbox_content_hash = models.CharField(max_length=100)
    # Dropbox file id
    dropbox_file_id = models.CharField(max_length=50)
    # Dropbox share url - This might be temporary if thumbnails are saved on google storage instead
    dropbox_share_url = models.URLField(blank=True, null=True)
    # File size as estimated from dropbox in bytes
    file_size = models.BigIntegerField()

    # Boolean flag to accommodate videos.
    # This could be abstracted away as "Content" with different "Content Type" classes
    # but since the content is mostly images, videos are parked under "Image" as a special type
    is_video = models.BooleanField(default=False)

    # Processed flag. A general flag to indicate if the image went through the custom processing pipeline
    # This will be initially only have metadata retrieved but will later include thumbnail creation/storage
    # and additional ML processing.
    requires_processing = models.BooleanField(default=True)

    # Content specific information extracted from the EXIF by dropbox
    time_taken = models.DateTimeField(blank=True, null=True)
    # In an ideal world, height/weight & lat/long would be separate classes but seems needless here and are stored as pure values
    height = models.IntegerField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    # Only relevant for video
    duration = models.IntegerField(blank=True, null=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.dropbox_file_name

    class Meta:
        ordering = ("-created",)
