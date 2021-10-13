from django.conf import settings
from django.db import models
from django.urls import reverse
from googleapiclient import model
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

    # History of model instance changes
    history = HistoricalRecords()

    # TODO: Create a model manager to generate a semantic name from
    # the camera trap ID, the microsite name & the date retrieved
    # to have a semantic folder structure

    def save(self, *args, **kwargs):
        # If the object is being created for the first time, create a GDrive directory
        if not self.id:
            client = GdriveClient()
            folder_name = f"{self.camera_trap.trap_id} - {self.date_retrieved}"
            self.gdrive_link = client.create_folder(folder_name)
        if self.upload_complete:
            client = GdriveClient()
            response = client.list_directory(self.gdrive_link.split("/")[-1])

            for img_dict in response["files"]:
                # Get or create to make sure duplicate objects aren't created by admin changes
                img_obj, created = Image.objects.get_or_create(
                    upload=self, filename=img_dict["name"], gdrive_id=img_dict["id"], mime_type=img_dict["mimeType"]
                )

        super(Upload, self).save(*args, **kwargs)

    def __str__(self):
        return self.camera_trap.trap_id

    class Meta:
        ordering = ("-created",)


class ImageMeta(TimeStampedModel):
    # A deterministic hash of the image metadata and its content for deduplication purposes
    image_hash = models.CharField(max_length=100, unique=True, blank=True, null=True)

    # Date taken
    date_taken = models.DateField()

    # TODO: incomplete set of meta attributes

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.gdrive_id

    class Meta:
        ordering = ("-created",)


# Each processed Image from an upload
# This is auto-created in the background after an upload to Google Drive has been finalized
# It is auto-updated later in the stream
class Image(TimeStampedModel):
    # Specific camera trap upload the images are linked to
    upload = models.ForeignKey(Upload, on_delete=models.PROTECT)
    # Original filename
    filename = models.CharField(max_length=250)
    # Initial Google Drive id. This is obsolete once it moves to Google storage
    gdrive_id = models.CharField(max_length=100, unique=True)
    # Gdrive Media type
    mime_type = models.CharField(max_length=100)

    # Google storage id. Empty initially but populated once it is moved
    gstorage_id = models.CharField(max_length=100, unique=True, blank=True, null=True)

    # Meta information from the image content itself
    meta = models.OneToOneField(ImageMeta, on_delete=models.PROTECT, blank=True, null=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.gdrive_id

    class Meta:
        ordering = ("-created",)
