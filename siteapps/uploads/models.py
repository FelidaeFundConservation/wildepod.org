from django.conf import settings
from django.db import models
from django.urls import reverse
from locations.models import CameraTrap
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .util import GdriveClient


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
    error_effect = models.CharField("Error's effect", max_length=100, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.error_effect

    class Meta:
        ordering = ("-created",)


class CameraTrapAction(TimeStampedModel):
    action = models.CharField("Last action taken", max_length=100, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.action

    class Meta:
        ordering = ("-created",)


# Model to log upload events.
class Upload(TimeStampedModel):
    # Camera trap the uploads are linked to
    camera_trap = models.ForeignKey(CameraTrap, on_delete=models.PROTECT)

    # Date the SD card was retrieved
    date_retrieved = models.DateField()

    # Last action on the camera trap
    last_action = models.ForeignKey(CameraTrapAction, on_delete=models.PROTECT)

    # Uploader
    volunteer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    # Errors & effects
    error = models.ForeignKey(UploadError, blank=True, null=True, on_delete=models.PROTECT)
    error_effect = models.ForeignKey(UploadErrorEffect, blank=True, null=True, on_delete=models.PROTECT)

    # Any uploader comments associated with the SD card
    comments = models.TextField(blank=True, null=True)

    # Auto generated grive link this upload is linked to
    gdrive_link = models.URLField()

    # Upload status. This defaults to false. After gdrive upload has been completed, this should be set to true by the uploader
    upload_complete = models.BooleanField("Upload to Google Drive complete?", default=False)

    # Processing status. This defaults to false. After the uploader marks upload as complete, all the images should be moved & processed
    # After that, this flag will be set on the upload.
    processed = models.BooleanField(default=False)

    # History of model instance changes
    history = HistoricalRecords()

    # TODO: Create a model manager to generate a semantic name from
    # the camera trap ID, the microsite name & the date retrieved
    # to have a semantic folder structure

    def save(self, *args, **kwargs):
        client = GdriveClient()
        folder_name = f"{self.camera_trap.trap_id} - {self.date_retrieved}"
        self.gdrive_link = client.create_folder(folder_name)
        super(Upload, self).save(*args, **kwargs)

    def __str__(self):
        return self.camera_trap.trap_id

    class Meta:
        ordering = ("-created",)


# Each processed Image from an upload
# This is auto-created in the background after images move from an SD card
# to a gdrive location to google storage


class Image(TimeStampedModel):
    # An image ID generated as a unique identifier from the content of the image
    # Ideally a hash of the entire image or exif metadata (this might cause collisions)
    image_id = models.CharField(max_length=100, unique=True)
    # Camera trap the uploads are linked to
    upload = models.ForeignKey(Upload, on_delete=models.PROTECT)

    # TODO: This requires the pipeline in the background to be setup to figure out
    # what fields are required

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.camera_trap

    class Meta:
        ordering = ("-created",)
