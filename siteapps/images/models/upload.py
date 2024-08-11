import os
import uuid
from urllib.parse import quote

import dropbox
from django.conf import settings
from django.db import models
from locations.models import CameraStation
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

# Create a dropbox client
dbx = dropbox.Dropbox(
    app_key=settings.DROPBOX_APP_KEY,
    app_secret=settings.DROPBOX_APP_SECRET,
    oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
)


class CameraStationAction(TimeStampedModel):
    action = models.TextField("Last action taken", unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.action

    class Meta:
        ordering = ("-created",)


class TimeCorrection(TimeStampedModel):
    # The time to offset the upload images' timestamps
    years = models.IntegerField(default=0, blank=True)
    months = models.IntegerField(default=0, blank=True)
    days = models.IntegerField(default=0, blank=True)
    hours = models.IntegerField(default=0, blank=True)
    minutes = models.IntegerField(default=0, blank=True)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    # The date of the daylight savings shift the upload crossed
    daylight_savings = models.DateField(null=True, blank=True)

    # When the time fix transformation was applied, if it has been already
    applied_at = models.DateTimeField(null=True, blank=True)


# Rename to the upload id
def rename_data_sheet(instance, filename):
    ext = filename.split(".")[-1]
    filename = f"{instance.id}.{ext}"

    return os.path.join("data_sheets/", filename)


# Model to log upload events.
class Upload(TimeStampedModel):
    # UUID for the upload
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Volunteer-uploaded file containing filled data sheet
    data_sheet = models.FileField(upload_to=rename_data_sheet, null=True, blank=True)

    # Camera station the uploads are linked to
    camera_station = models.ForeignKey(CameraStation, on_delete=models.PROTECT)

    # Date the SD card was retrieved
    date_retrieved = models.DateTimeField()

    # Last action on the camera station
    last_action = models.ForeignKey(CameraStationAction, on_delete=models.PROTECT)

    # Uploader
    volunteer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    time_correction = models.ForeignKey(
        TimeCorrection, on_delete=models.PROTECT, null=True, blank=True, related_name="upload"
    )

    # Details of any time errors in the set.
    time_error_details = models.TextField(blank=True, null=True)

    # Information on the last time fix that was applied to the upload set.
    time_fix_details = models.TextField(blank=True, null=True)

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
    # Absolute url for direct uploading to the Wildepod dropbox account
    dropbox_direct_url = models.URLField(blank=True, null=True)

    # Upload status. This defaults to false. After dropbox upload has been completed, this should be set to true by the uploader
    upload_complete = models.BooleanField("Upload to Dropbox complete?", default=False)

    # Processed flag. This defaults to false. After all images have been processed, this flag will be set to true.
    processed = models.BooleanField("Processed upload?", default=False)

    # Add a priority setting for uploads. This will be used to prioritize uploads in the queue
    priority = models.CharField(
        "Priority",
        max_length=1,
        choices=(
            ("1", "Low"),
            ("2", "Medium"),
            ("3", "High"),
            ("4", "Highest"),
        ),
        default="1",
        db_index=True,
    )

    # Allow uploading the images in multiple ways
    upload_method = models.CharField(
        "Upload Method",
        max_length=1,
        choices=(
            ("E", "Upload via Dropbox external link"),
            ("D", "Upload from Wildepod Dropbox account (Wildepod Credentials Required!)"),
        ),
        default="E",
    )

    # History of model instance changes
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        is_prod = "prod" in settings.WSGI_APPLICATION
        is_staging = "staging" in settings.WSGI_APPLICATION
        # If the object is being created for the first time, create a Dropbox request url and populate relevant fields
        if self._state.adding and (is_prod or is_staging):
            # First auto-generate a foldername. Always lowercase since dropbox is case insensitive anyway
            self.dropbox_folder_name = (
                f"{self.date_retrieved.date()} - {self.camera_station.micro_site.macro_site.name} -"
                f" {self.camera_station.station_id}".lower()
            )
            # Generate the full path
            self.dropbox_folder_path = f"/{self.dropbox_folder_name}"
            if self.upload_method == "E":
                # Now create a folder request. The path will always be relative to the app root.
                # The entire directory structure, for now, will be flat under the App directory
                response = dbx.file_requests_create(
                    title=self.dropbox_folder_name, destination=self.dropbox_folder_path
                )
                # The response is a FileRequest object. Error handling/exceptions will be handled by the python package
                self.dropbox_request_id = response.id
                self.dropbox_request_url = response.url
                self.dropbox_request_open = response.is_open
            else:
                response = dbx.files_create_folder(self.dropbox_folder_path)

                # Construct and encode the absolute dropbox url
                self.dropbox_direct_url = settings.DROPBOX_URL_PREFIX + quote(self.dropbox_folder_path, safe=":/")

        super().save(*args, **kwargs)

    def __str__(self):
        return self.dropbox_folder_name

    class Meta:
        ordering = ("-created",)
        unique_together = [["camera_station", "date_retrieved"]]

        # Keep commented while testing to check effect on performance
        # indexes = [
        #     models.Index(fields=['camera_station',]),
        #     models.Index(fields=['priority',])
        # ]
