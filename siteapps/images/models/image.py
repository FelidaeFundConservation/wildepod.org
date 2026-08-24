# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import uuid
from datetime import datetime

from django.conf import settings
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone
from locations.models import CameraStation
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .annotator import Annotator
from .raw_sql import *
from .upload import Upload


class StaffReviewFlagSource(models.TextChoices):
    """How an image came to be flagged for staff review."""

    # An annotator deliberately ticked "Flag for Staff Review" and gave a reason
    MANUAL = "manual", "Flagged by annotator"
    # auto_flag_for_staff() tripped the skip threshold; no one asked for review
    AUTO_SKIPS = "auto_skips", "Auto-flagged"


class StaffReviewFlagReason(models.TextChoices):
    """Why an annotator asked for staff review.

    Required whenever an annotator flags an image, so the review queue can be triaged and
    so deliberate flags can be told apart from auto-flagged noise.
    """

    # Named for the work that is needed rather than how unsure the annotator feels. "I cannot
    # tell what this is" is a Skip, not a flag, so it deliberately has no option here.
    SPECIES_ID = "species_id", "Species ID needs review"
    BBOX_PROTOCOL = "bbox_protocol", "Bounding box protocol needs review"
    OTHER = "other", "Other"


# Bounding Box manager. For now, this simply returns "valid" bounding boxes as determined
# by the accept/reject ratio
class ImageManager(models.Manager):
    def annotated(self):
        # Combining multiple aggregations with annotate() will yield the wrong results because joins are used instead of subqueries
        # https://docs.djangoproject.com/en/4.0/topics/db/aggregation/#combining-multiple-aggregations

        return self.annotate(
            num_objects=models.functions.Coalesce(models.Count("boundingbox", distinct=True), 0),
            # new=models.functions.Coalesce(models.Max("boundingbox__num_accepted"), 0.0),
            num_bbox_checked_by=models.functions.Coalesce(models.Count("bbox_checked_by", distinct=True), 0),
            num_species_checked_by=models.functions.Coalesce(models.Count("species_checked_by", distinct=True), 0),
            num_activity_checked_by=models.functions.Coalesce(models.Count("activity_checked_by", distinct=True), 0),
        )

    # Calculates the proportion of images per macro site.
    def proportion_per_macrosite(self):
        total_count = self.count()
        proportion = self.values("upload__camera_station__micro_site__macro_site__name").annotate(count=models.Count("id")).order_by()
        for item in proportion:
            item["proportion"] = item["count"] / total_count
        return proportion

    # Calculates the proportion of images per camera station.
    def proportion_per_camera_station(self):
        total_count = self.count()
        proportion = self.values("upload__camera_station__station_id").annotate(count=models.Count("id")).order_by()
        for item in proportion:
            item["proportion"] = item["count"] / total_count
        return proportion


# Each processed Image from an upload
# This is auto-created in the background after an upload to dropbox is finished
# It is auto-updated later in the stream
class Image(TimeStampedModel):
    # UUID for the image
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Specific camera station upload the images are linked to
    upload = models.ForeignKey(Upload, on_delete=models.PROTECT, related_name="images")
    # Dropbox filename.
    # NOTE: Dropbox requests prepend files with the "Uploader's name" which should be removed to get the actual filename although not useful
    dropbox_file_name = models.TextField()
    # The full path of the file. This is especially required if the upload has a directory structure
    dropbox_file_path = models.TextField()
    # The display path. This is the actual file name with original casing (Dropbox is case insensitive)
    dropbox_file_path_display = models.TextField()
    # Dropbox's 64 character content hash. This can be used for deduplication and offsets the need to compute a local content hash
    # https://www.dropbox.com/developers/reference/content-hash
    dropbox_content_hash = models.CharField(max_length=100, db_index=True)
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

    # These are the nearby images in the upload set
    context_image_gcloud_paths = models.TextField(null=True, blank=True)

    # Processed flag. A general flag to indicate if the image went through the custom processing pipeline
    # This will be initially only have metadata retrieved but will later include thumbnail creation/storage
    # and additional ML processing.
    processed = models.BooleanField(default=False)

    # Content specific information extracted from the EXIF by dropbox
    trigger_timestamp = models.DateTimeField(blank=True, null=True, db_index=True)
    time_correction_applied = models.BooleanField(default=False)

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
    social_media_worthy = models.IntegerField(default=0)
    bbox_checked_by = models.ManyToManyField(Annotator, related_name="checked_bbox_for_images", blank=True)
    bbox_skipped_by = models.ManyToManyField(Annotator, related_name="skipped_bbox_for_images", blank=True)
    species_checked_by = models.ManyToManyField(Annotator, related_name="checked_bbox_for_species", blank=True)
    species_skipped_by = models.ManyToManyField(Annotator, related_name="skipped_bbox_for_species", blank=True)
    activity_checked_by = models.ManyToManyField(Annotator, related_name="checked_bbox_for_activity", blank=True)
    activity_skipped_by = models.ManyToManyField(Annotator, related_name="skipped_bbox_for_activity", blank=True)

    # Save the detections from the cloud run for re-use. This is a list in string form that should be converted back to a list.
    species_ai_detections = models.CharField(max_length=1024, null=True)

    # Flag for Staff Review. True when any pipeline below needs review, so the staff review
    # queue and the search page can ask "is this image in review at all" in one column.
    staff_review_needed = models.BooleanField(default=False)

    # Which pipelines the review applies to. The skip threshold is counted per pipeline but
    # used to set one global flag, so three volunteers failing to identify the species also
    # pulled the image out of the activity pool -- where it was very likely still annotatable,
    # since knowing what an animal is doing does not require knowing what it is.
    #
    # A deliberate flag from an annotator sets both: they are asking staff to look at the
    # image, not at one pipeline's worth of it. An automatic flag sets only the pipeline whose
    # threshold was crossed.
    species_review_needed = models.BooleanField(default=False)
    activity_review_needed = models.BooleanField(default=False)

    # Provenance for staff_review_needed, so staff can triage the review queue and so the
    # volume of deliberate flags can be told apart from images flagged automatically.
    # All three are cleared whenever staff_review_needed goes back to False.
    flag_source = models.CharField(
        max_length=16,
        choices=StaffReviewFlagSource.choices,
        blank=True,
        default="",
        help_text="Whether this image was flagged deliberately by an annotator or automatically.",
    )
    flag_reason = models.CharField(
        max_length=32,
        choices=StaffReviewFlagReason.choices,
        blank=True,
        default="",
        help_text="Why the annotator flagged this image for staff review.",
    )
    # Free text, only used alongside StaffReviewFlagReason.OTHER
    flag_reason_detail = models.CharField(max_length=250, blank=True, default="")
    flagged_by = models.ForeignKey(
        Annotator,
        on_delete=models.SET_NULL,
        related_name="flagged_images",
        null=True,
        blank=True,
    )
    flagged_at = models.DateTimeField(null=True, blank=True)
    # When staff last dealt with this image, by annotating it or clearing the flag in bulk.
    # The skip counters never reset, so once an image is past the automatic threshold every
    # later skip satisfies it again -- without this, clearing the flag would last only until
    # the next volunteer skipped it, and the image would bounce back to staff for ever.
    # Deliberate flagging by an annotator is unaffected: a person asking for help is a fresh
    # request, not the counter tripping a second time.
    staff_reviewed_at = models.DateTimeField(null=True, blank=True)

    # Flag for Reported Images. This field is used to indicate images that have been reported by users for review.
    image_reported = models.BooleanField(default=False)

    # Precomputed pipeline stage-related flags.
    category_pipeline_complete = models.BooleanField(default=False)
    species_pipeline_complete = models.BooleanField(default=False)
    activity_pipeline_complete = models.BooleanField(default=False)

    has_animals = models.BooleanField(default=False)
    has_humans = models.BooleanField(default=False)
    has_vehicles = models.BooleanField(default=False)
    has_wild_animals = models.BooleanField(default=False)
    has_cats = models.BooleanField(default=False)

    # Has at least one bbox above confidence threshold
    has_bbox_above_confidence_threshold = models.BooleanField(default=False)

    # Has uncertain bboxes that are yet to be validated
    has_uncertain_bbox = models.BooleanField(default=False)

    # Additional field to support incremental migration to the new precomputed flags
    use_precomputed_flags = models.BooleanField(default=False)

    # Mirrors the same field in Upload to allow conditional uniqueness constraint. Shouldn't be directly modified.
    deleted = models.BooleanField(default=False)

    # Custom manager
    objects = ImageManager()

    def __str__(self):
        return self.dropbox_file_name

    def flag_for_staff_review(
        self, source, annotator=None, reason="", reason_detail="", pipelines=None, save=True
    ):
        """Flags this image for staff review, recording where the flag came from.

        Use this rather than assigning ``staff_review_needed`` directly so provenance and
        the flag itself can never drift apart.

        Arguments
        ---
            - source (StaffReviewFlagSource): MANUAL for a deliberate annotator flag,
              AUTO_SKIPS when the skip threshold tripped.
            - annotator (Annotator | None): Who flagged it. None for automatic flags.
            - reason (str): A StaffReviewFlagReason value. Required for MANUAL flags.
            - reason_detail (str): Free text, only meaningful with reason OTHER.
            - pipelines (iterable[str] | None): Which pipelines the review applies to. None
              means all of them, which is right for a deliberate flag -- the annotator is
              asking staff to look at the image, not at one pipeline's worth of it. The
              automatic threshold passes only the pipeline it tripped on, so an image nobody
              could name the species of stays available for activity annotation.
        """
        self.staff_review_needed = True

        for pipeline in pipelines if pipelines is not None else self.REVIEW_PIPELINES:
            setattr(self, f"{pipeline}_review_needed", True)

        self.flag_source = source
        self.flag_reason = reason or ""
        self.flag_reason_detail = reason_detail or ""
        self.flagged_by = annotator
        self.flagged_at = timezone.now()

        if save:
            self.save()

    # The pipelines a volunteer can be asked to work on. bbox is deliberately absent: the
    # bbox_skipped_by counter has no writer anywhere in the project, so its threshold can
    # never be crossed and a bbox review flag would never be set.
    REVIEW_PIPELINES = ("species", "activity")

    @classmethod
    def volunteer_pool_filters(cls, pipeline):
        """What an image must look like to be offered to a volunteer in one pipeline.

        Kept here because three separate queries need it -- the pipeline queries, precomputed
        queue eligibility, and the queue's own image list -- and an image slipping back into
        the pool through whichever one was missed is not something anybody would notice.

        staff_reviewed_at is the "never again" part: once an image has been through staff
        review, however it got there, it does not go back to volunteers. Staff can still hand
        it to an expert, which goes through an assigned ImageQueue and skips these filters.

        Arguments
        ---
            - pipeline (str): One of REVIEW_PIPELINES. Only that pipeline's review flag is
              consulted, so an image nobody could identify by species stays available for
              activity annotation.
        """
        if pipeline not in cls.REVIEW_PIPELINES:
            raise ValueError(f"Unknown review pipeline: {pipeline}")

        return {
            f"{pipeline}_review_needed": False,
            "image_reported": False,
            "staff_reviewed_at__isnull": True,
        }

    # What "not flagged" looks like, as field values. Shared with the bulk clear in
    # BulkImageActionView, which applies it through queryset.update() rather than instance by
    # instance -- keeping the two in one place means a provenance field added later cannot be
    # cleared by one path and left behind by the other.
    CLEARED_STAFF_REVIEW_FIELDS = {
        "staff_review_needed": False,
        "species_review_needed": False,
        "activity_review_needed": False,
        "flag_source": "",
        "flag_reason": "",
        "flag_reason_detail": "",
        "flagged_by": None,
        "flagged_at": None,
    }

    @classmethod
    def cleared_staff_review_values(cls):
        """CLEARED_STAFF_REVIEW_FIELDS plus a review timestamp of now.

        Separate from the constant because the timestamp has to be read at the moment of
        clearing, not at import. Use this rather than the constant wherever staff are actually
        resolving an image, so the automatic threshold knows not to re-flag it.
        """
        return {**cls.CLEARED_STAFF_REVIEW_FIELDS, "staff_reviewed_at": timezone.now()}

    def clear_staff_review_flag(self, save=True):
        """Clears the staff review flag and its provenance, and records the review."""
        for field, value in self.cleared_staff_review_values().items():
            setattr(self, field, value)

        if save:
            self.save()

    @property
    def flag_reason_display(self):
        """Human readable flag reason for the staff review queue, or "" if unflagged."""
        if not self.staff_review_needed:
            return ""

        if self.flag_source == StaffReviewFlagSource.AUTO_SKIPS:
            return StaffReviewFlagSource.AUTO_SKIPS.label

        if self.flag_reason == StaffReviewFlagReason.OTHER and self.flag_reason_detail:
            return f"{StaffReviewFlagReason.OTHER.label}: {self.flag_reason_detail}"

        if self.flag_reason:
            try:
                return StaffReviewFlagReason(self.flag_reason).label
            except ValueError:
                # A reason that has since been retired from the taxonomy. Show it rather than
                # raising, so old rows never take down the page they appear on.
                return self.flag_reason.replace("_", " ").capitalize()

        # Flagged before this field existed, or flagged without a reason
        return "Reason not recorded"

    @staticmethod
    def get_total_images():
        """Returns the number of uploaded images"""
        return Image.objects.count()

    @staticmethod
    def get_total_images_processed():
        return Image.objects.filter(processed=True).count()

    @staticmethod
    def get_total_images_not_processed():
        return Image.objects.filter(processed=False).count()

    @staticmethod
    def get_total_images_annotated_species(species_name=None):
        """
        Returns the images with annotated species. This is made through bounding_box
        """
        if species_name == "human":
            return Image.objects.filter(boundingbox__species__name_id=8).distinct()
        else:
            return (
                Image.objects.filter(boundingbox__species__isnull=False)
                .exclude(boundingbox__species__name_id=8)
                .distinct()
            )

    @staticmethod
    def get_total_images_annotated_category(category_name):
        """
        Returns the images with annotated category. This is made through bounding_box
        """
        return Image.objects.filter(boundingbox__category__name=category_name).distinct()

    @staticmethod
    def get_total_images_annotated_exclude_category(category_name):
        """
        Returns the images without the annotated category. This is made through bounding_box
        """
        return Image.objects.exclude(boundingbox__category__name=category_name).distinct()

    @staticmethod
    def get_total_images_annotated_activity(category_name="animal"):
        """
        Returns the images with annotated activity. This is made through bounding_box
        """
        category = [5, 6, 7, 8] if category_name == "human" else [1, 2, 3, 4]
        return Image.objects.filter(boundingbox__activity__name__in=category).distinct()

    @staticmethod
    def get_total_images_priorities():
        """Returns the number of uploaded images by priority"""
        priorities = Upload.objects.annotate(total=Count("images"))
        pri_1 = priorities.filter(priority=1)
        pri_2 = priorities.filter(priority=2)
        pri_3 = priorities.filter(priority=3)
        pri_4 = priorities.filter(priority=4)
        return {
            "priority_1": sum(pr.total for pr in pri_1),
            "priority_2": sum(pr.total for pr in pri_2),
            "priority_3": sum(pr.total for pr in pri_3),
            "priority_4": sum(pr.total for pr in pri_4),
        }

    @staticmethod
    def get_untouched_images():
        """Returns the number of untouched images, no accepted or rejected bounding box"""

        # !!! have to return images, not bounding boxes.

        from images.models.annotation import BoundingBox

        return (
            BoundingBox.objects.exclude(accepted_by__isnull=False)
            .exclude(rejected_by__isnull=False)
            .values("image_id")
            .distinct()
            .count()
        )

    """  FROM RAW SQL """

    @staticmethod
    def get_species_annotated(species_ids):
        return get_species_annotated(species_ids)

    class Meta:
        ordering = (
            "trigger_timestamp",
            "-created",
        )

        indexes = [
            models.Index(fields=['trigger_timestamp', 'upload'], name='idx_image_trigger_upload'),
            models.Index(fields=['upload', 'trigger_timestamp'], name='idx_image_upload_trigger_date'),
            models.Index(
                fields=['-trigger_timestamp', '-id', '-social_media_worthy'],
                name='idx_image_popular_sort',
                condition=Q(social_media_worthy__gt=0)
            ),
            models.Index(
                fields=['social_media_worthy', 'trigger_timestamp', 'id'],
                name='idx_image_social_media_worthy'
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["dropbox_content_hash"], condition=Q(deleted=False), name="unique_active_dropbox_hash"
            )
        ]


# A precomputed batch of images to annotate
class ImageQueue(TimeStampedModel):
    # Which stage the images are in
    pipeline_name = models.CharField(
        "Pipeline",
        max_length=250,
        choices=(
            ("SPECIES", "Species"),
            ("ACTIVITY_HUMAN", "Human Activity"),
            ("ACTIVITY_ANIMAL", "Animal Activity"),
        ),
        default="SPECIES",
    )
    # The annotator this queue is currently assigned to.
    assigned_to = models.ForeignKey(
        Annotator, on_delete=models.PROTECT, related_name="assigned_to_annotator", default=None, null=True
    )

    # Don't assign this queue to these annotators anymore
    checked_by = models.ManyToManyField(Annotator, related_name="checked_queue", blank=True)

    # The images to be annotated
    images = models.ManyToManyField(Image, related_name="queue", blank=True)
    # Serves as a pseudo-index to exclude images before another
    partition = models.DateTimeField(default=datetime.min)

    # The order the images were searched in, as a list of image id strings.
    #
    # A many to many has no order of its own, so reading images.all() falls back to
    # Image.Meta.ordering -- trigger_timestamp. For a queue built from a search that is simply
    # the wrong order: a staff member who sorted by flagger, or by newest first, was served
    # their batch oldest-capture-first regardless.
    #
    # Empty for the automatically precomputed queues, which have no meaningful order of their
    # own and are served by pipeline priority as before.
    image_order = models.JSONField(default=list, blank=True)

    # How far through image_order this queue has been worked, as an index into it. Used
    # instead of `partition` for searched queues: partition is a timestamp, which can only
    # express a position in capture order.
    position = models.PositiveIntegerField(default=0)

    def ordered_images(self):
        """The queue's images in search order, skipping any that have since been deleted.

        Falls back to the plain related manager for queues with no recorded order, which is
        every automatically precomputed one.
        """
        if not self.image_order:
            return list(self.images.all())

        by_id = {str(image.id): image for image in self.images.all()}

        return [by_id[image_id] for image_id in self.image_order if image_id in by_id]

    def add_images(self, images):
        """Adds images to the queue, keeping image_order in step with membership.

        Use this rather than ``queue.images.add(...)`` on a queue that has a recorded order.
        ordered_images() serves only what image_order lists, so anything added straight to the
        many to many is in the queue but never shown -- which is how bulk-assigning work to an
        expert who already had a search queue silently delivered them nothing.

        Appending also puts the new images after whatever the queue has already been worked
        through, so a queue that had been finished picks up again at the first new image.

        Arguments
        ---
            - images (iterable[Image]): The images to add. Ones already present are ignored.
        """
        images = list(images)
        self.images.add(*images)

        if not self.image_order:
            # No recorded order, so ordered_images() falls back to the related manager and
            # already sees these. Recording an order here would only freeze an arbitrary one.
            return

        known = set(self.image_order)
        self.image_order = list(self.image_order) + [
            str(image.id) for image in images if str(image.id) not in known
        ]
        self.save(update_fields=["image_order"])

    def advance_past(self, image_id):
        """Moves the cursor to just after the given image, if it is in this queue's order.

        Called with whatever was just annotated rather than simply incrementing, so the cursor
        stays right even when someone jumps around the queue with the grid.

        Arguments
        ---
            - image_id (str | UUID): The image that has just been dealt with.
        """
        if not self.image_order:
            return False

        try:
            index = self.image_order.index(str(image_id))
        except ValueError:
            return False

        self.position = index + 1
        self.save(update_fields=["position"])

        return True

    class Meta:
        # Newest first, because an annotator can hold more than one queue -- their own search
        # and one a staff member assigned to them -- and get_precomputed_queue() takes
        # .first(). With no ordering that pick is whatever the database happens to return, so
        # which batch someone is handed comes down to luck. Newest wins: the most recent
        # assignment is the one that was just made for them.
        ordering = ("-created",)
