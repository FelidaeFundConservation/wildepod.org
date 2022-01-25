import uuid

from django.conf import settings
from django.db import models
from locations.models import CameraStation
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .annotator import Annotator
from .upload import Upload


# Bounding Box manager. For now, this simply returns "valid" bounding boxes as determined
# by the accept/reject ratio
class ImageManager(models.Manager):
    def annotated(self):
        return self.annotate(
            num_objects=models.functions.Coalesce(models.Count("boundingbox"), 0),
            num_viewed_by_for_bbox=models.functions.Coalesce(models.Count("viewed_by_for_bbox"), 0),
            num_viewed_by_for_species=models.functions.Coalesce(models.Count("viewed_by_for_species"), 0),
        )


# Each processed Image from an upload
# This is auto-created in the background after an upload to dropbox is finished
# It is auto-updated later in the stream
class Image(TimeStampedModel):
    # UUID for the image
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

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
    processed = models.BooleanField(default=False)

    # Content specific information extracted from the EXIF by dropbox
    trigger_timestamp = models.DateTimeField(blank=True, null=True)
    # In an ideal world, height/weight & lat/long would be separate classes but seems needless here and are stored as pure values
    height = models.IntegerField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    # Only relevant for video
    duration = models.IntegerField(blank=True, null=True)

    # Thumbnail location. Only populated for images & is directly saved into a bucket with the url set.
    # These thumbnails are transient, i.e. there is no guarantee that they will persist
    thumbnail_gcloud_path = models.CharField(max_length=250, blank=True, null=True)

    # TODO: Might need to remove/refactor these
    # Bookkeeping fields. These are used as convenience fields to track users and images they've seen/skipped
    viewed_by_for_bbox = models.ManyToManyField(Annotator, related_name="viewed_images_for_bbox", blank=True)
    skipped_by_for_bbox = models.ManyToManyField(Annotator, related_name="skipped_images_for_bbox", blank=True)
    viewed_by_for_species = models.ManyToManyField(Annotator, related_name="viewed_images_for_species", blank=True)
    skipped_by_for_species = models.ManyToManyField(Annotator, related_name="skipped_images_for_species", blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    # Custom manager
    objects = ImageManager()

    def __str__(self):
        return self.dropbox_file_name

    class Meta:
        ordering = ("-created",)
