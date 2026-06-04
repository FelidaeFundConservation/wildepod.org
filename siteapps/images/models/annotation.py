import uuid

from django.conf import settings
from django.db import models
from django.db.models import Case, Count, Exists, ExpressionWrapper, F, OuterRef, Q, Value, When
from django.db.models.functions import Coalesce
from django.forms import BooleanField
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .image import Annotator, Image


class BaseAnnotationManager(models.Manager):
    """
    Base Manager that filters annotations by the stored `validity` field.
    The field is populated by compute_validity() in processors/annotation.py
    and persisted by calculate*AnnotationFlags in views/annotation.py.

    annotated() is kept as a passthrough so subclasses (BoundingBoxManager)
    can chain additional annotations on top via super().annotated().
    """

    def annotated(self):
        # No-op now that validity is stored on the model. Subclasses may
        # extend with additional .annotate() calls.
        return self.get_queryset()

    def valid(self):
        return self.filter(validity="VALID")

    def uncertain(self):
        return self.filter(validity="UNCERTAIN")

    def valid_or_uncertain(self):
        return self.filter(validity__in=["VALID", "UNCERTAIN"])


# Certainty annotations for bounding boxes
class BoundingBoxManager(BaseAnnotationManager):

    # TODO: Fix this
    # This quickly filters only boxes that have at least one animal category tag associated with it
    # This ideally should only return boxes that has a consensus that the category is animal
    # This requires overall vote consensus to be implemented

    # TODO: This is an untested hack to quickly flag if there is an animal tag associated with this box
    # This doesn't consider vote differences nor overall consensus for the animal tag and must be fixed.
    def annotated(self):
        return (
            super()
            .annotated()
            .annotate(
                is_animal=ExpressionWrapper(
                    Q(category__isnull=False) & Q(category__name="animal"), output_field=models.BooleanField()
                ),
                is_person=ExpressionWrapper(
                    Q(category__isnull=False) & Q(category__name="person"), output_field=models.BooleanField()
                ),
                is_vehicle=ExpressionWrapper(
                    Q(category__isnull=False) & Q(category__name="vehicle"), output_field=models.BooleanField()
                ),
                is_species_tagged=ExpressionWrapper(
                    Q(category__isnull=False) & Q(category__name="animal") & Q(species__isnull=False),
                    output_field=models.BooleanField(),
                ),
                # TODO: Use the field in the SpeciesName model to identify non-domestic species
                is_nondomestic_species=ExpressionWrapper(
                    Q(category__isnull=False)
                    & Q(category__name="animal")
                    & Q(species__isnull=False)
                    & ~Q(
                        species__name__name__in=[
                            "Human",
                            "Domestic cat",
                            "Domestic dog",
                            "Domestic horse",
                            "Cow, Cattle",
                            "Goat (domestic)",
                            "Sheep (domestic)",
                        ]
                    ),
                    output_field=models.BooleanField(),
                ),
            )
        )

    def is_animal(self):
        return self.annotated().filter(is_animal=True)

    def is_person(self):
        return self.annotated().filter(is_person=True)

    def is_vehicle(self):
        return self.annotated().filter(is_vehicle=True)

    def is_species_tagged(self):
        return self.annotated().filter(is_species_tagged=True)

    def is_nondomestic_species(self):
        return self.annotated().filter(is_nondomestic_species=True)


# Certainty annotations for categories
class CategoryManager(BaseAnnotationManager):
    # Add ordering. The previous `vote_diff` ordering is dropped because the
    # weighted score is no longer materialized on the queryset; confidence and
    # timestamps remain useful tiebreakers.
    def valid(self):
        return super().valid().order_by("-confidence", "-created", "-modified")

    def valid_or_uncertain(self):
        return super().valid_or_uncertain().order_by("-confidence", "-created", "-modified")


# Certainty annotations for activites
class ActivityManager(BaseAnnotationManager):
    def valid(self):
        return super().valid().order_by("-confidence", "-created", "-modified")

    def valid_or_uncertain(self):
        return super().valid_or_uncertain().order_by("-confidence", "-created", "-modified")


# Shared validity enum used across all annotation models (BoundingBox, Category,
# Species, Activity). NULL on the field represents UNSEEN (no votes / no
# annotations). Category/Species/Activity always have a creator whose vote
# contributes to one of these values; BoundingBox may be NULL when the
# cascade finds no child annotations.
class Validity(models.TextChoices):
    VALID = "VALID", "Valid"
    INVALID = "INVALID", "Invalid"
    UNCERTAIN = "UNCERTAIN", "Uncertain"


# Each annotation is a bounding box linked to an image
# Bounding boxes are identified by x,y,w,h where w,h are normalized width & height
# Each annotation has a creator that is either an ML model or a human
# Each annotation can be accepted/rejected by a human
# Each annotation has a primary class from MegaDetector i.e one of 'Animal', 'Person', 'Vehicle'
# and a secondary class that identifies the species
class BoundingBox(TimeStampedModel):
    # A unique identifier for the annotation
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The image the annotation is linked to
    image = models.ForeignKey(Image, on_delete=models.CASCADE)

    # Bounding box of the annotation. These values are normalized (0-1)
    x = models.FloatField()
    y = models.FloatField()
    w = models.FloatField()
    h = models.FloatField()

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_annotation")
    # Confidence. This is the probability that the annotation is correct which includes both bounding box & class
    # This is the score from the model if its a bot. It is 1 if its by a human initially
    # Later, the human confidence itself can be added in as a function of tenure
    confidence = models.FloatField(default=1.0)

    # The threshold of the bot that created the bounding box to show in the pipeline.
    confidence_threshold = models.FloatField(default=0.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_annotation", blank=True)

    # Bounding box validity. UNSEEN means no annotations exist (or all rejected);
    # other values come from the cascade rule in calculate*AnnotationFlags based
    # on child Category/Species/Activity validity.
    validity = models.CharField(
        "Validity",
        max_length=9,
        choices=Validity.choices,
        null=True,
        default=Validity.UNCERTAIN,
    )

    objects = BoundingBoxManager()

    def __str__(self):
        return (
            f"{self.image.upload.camera_station.micro_site.macro_site.name} |"
            f" {self.image.upload.camera_station.micro_site.name} | {self.id}"
        )

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Bounding Boxes"

        constraints = [
            models.CheckConstraint(check=Q(x__gte=0.0, x__lte=1.0), name="x_between_0_and_1"),
            models.CheckConstraint(check=Q(y__gte=0.0, y__lte=1.0), name="y_between_0_and_1"),
            models.CheckConstraint(check=Q(w__gte=0.0, w__lte=1.0), name="w_between_0_and_1"),
            models.CheckConstraint(check=Q(h__gte=0.0, h__lte=1.0), name="h_between_0_and_1"),
        ]

        indexes = [
            models.Index(fields=['-modified'], name='images_bbox_modified_idx'),
            models.Index(fields=['-created'], name='images_bbox_created_idx'),
            models.Index(fields=['image'], name='idx_bbox_image_id'),
            models.Index(fields=['image_id'], name='idx_boundingbox_image_id'),
        ]


class SpeciesSubgroup(TimeStampedModel):
    name = models.CharField("Subgroup Name", max_length=250, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = (
            "name",
            "-created",
        )
        verbose_name_plural = "Species Subgroups"


# Model to maintain different species types
class SpeciesName(TimeStampedModel):
    name = models.CharField("Common Name", max_length=250, unique=True)
    scientific_name = models.CharField(max_length=250, unique=True)

    # Species name is currently used and shown in the annotation widget
    active = models.BooleanField(default=True)

    # The categorization of the species type,
    # not to be confused with the species type itself
    species_group = models.CharField(
        "Species Group",
        max_length=250,
        choices=(
            ("HUMAN", "Human"),
            ("WILD", "Wild Animal"),
            ("DOMESTIC", "Domestic Animal"),
            ("VEHICLE", "Vehicle"),
            ("OTHER", "Other"),
        ),
        null=True,
        default=None,
    )

    subgroup = models.ForeignKey(SpeciesSubgroup, null=True, blank=True, on_delete=models.SET_NULL)

    is_bird = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        ordering = (
            "name",
            "-created",
        )
        verbose_name_plural = "Species List"


# TODO: Combine category & species into a single base model & inherit from it
# Each annotation is futher linked to an Annotation Type if the primary class is an animal
# This is the Species of the animal identified
class Category(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.CASCADE)

    # The main category of the detected object. This can be "Animal", "Human" or "Vehicle"
    # Unannotated is set when a box is created in Species or later, and used to filter Species-completed images in category stage
    name = models.CharField(
        max_length=12,
        choices=[("animal", "animal"), ("vehicle", "vehicle"), ("person", "person"), ("unannotated", "unannotated")],
    )

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_category_annotation")

    # This, if created by Megadetector, is the same confidence as the bounding box
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_category_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_category_annotation", blank=True)

    # Vote-derived validity. NULL = UNSEEN (no votes yet). Computed and saved
    # by calculate*AnnotationFlags via compute_validity().
    validity = models.CharField(
        max_length=9,
        choices=Validity.choices,
        null=True,
        default=None,
        db_index=True,
    )

    objects = CategoryManager()

    def __str__(self):
        return f"{self.id} | {self.name} | BBox: {self.bounding_box.id}"

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Category Annotations"

    @staticmethod
    def get_categories_group_by():
        return Category.objects.values("name").annotate(total=Count(1))


# Each annotation is futher linked to an Annotation Type if the primary class is an animal
# This is the Species of the animal identified
class Species(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.CASCADE)

    # The species of the animal
    name = models.ForeignKey(SpeciesName, on_delete=models.PROTECT)

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_species_annotation")

    # Confidence from the species detection model
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_species_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_species_annotation", blank=True)

    # Vote-derived validity. NULL = UNSEEN (no votes yet). Computed and saved
    # by calculate*AnnotationFlags via compute_validity().
    validity = models.CharField(
        max_length=9,
        choices=Validity.choices,
        null=True,
        default=None,
        db_index=True,
    )

    objects = CategoryManager()

    def __str__(self):
        return self.name.name

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Species Annotations"

        indexes = [
            models.Index(fields=['-modified'], name='images_species_modified_idx'),
            models.Index(fields=['-created'], name='images_species_created_idx'),
            models.Index(fields=['name', '-modified'], name='idx_species_name_modified'),
            models.Index(fields=['name', 'bounding_box'], name='idx_species_name_bbox'),
            models.Index(fields=['name_id', 'bounding_box_id'], name='idx_species_name_id_bbox'),
        ]

    @staticmethod
    def get_total_species():
        return Species.objects.all().count()

    @staticmethod
    def get_species_group_by():
        return (
            Species.objects.all()
            .annotate(species=F("name__name"))
            .values("species")
            .annotate(total=Count(1))
            .order_by("species")
        )

    @staticmethod
    def species_human_animal():
        """
        Get the total number of species that are human or not human.
        If a new human name is added, the list shuld be updated here.
        Better to create a broad category over SpeciesName.
        """
        human = (1, 56, 57, 58)
        animal = SpeciesName.objects.exclude(id__in=human).values_list("id", flat=True)
        return {"human": human, "animal": tuple(animal)}


# Names of different types of activity
class ActivityType(TimeStampedModel):
    name = models.CharField(max_length=250, unique=True)
    comments = models.TextField("Additional notes", null=True, blank=True)

    # The cateogory of the activity. Differenciates between activities that applies to humans or animals
    category = models.CharField(
        max_length=10,
        choices=[("animal", "animal"), ("human", "human")],
        default="animal",
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Activity Types"


# Each annotation also has an "activity" attached to it.
# This indicates the activity of the object in that specific image like eating, walking, resting etc
class Activity(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.CASCADE)

    # The activity type of the animal
    name = models.ForeignKey(ActivityType, on_delete=models.PROTECT)

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_activity_annotation")

    # Confidence from the species detection model
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_activity_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_activity_annotation", blank=True)

    # Vote-derived validity. NULL = UNSEEN (no votes yet). Computed and saved
    # by calculate*AnnotationFlags via compute_validity().
    validity = models.CharField(
        max_length=9,
        choices=Validity.choices,
        null=True,
        default=None,
        db_index=True,
    )

    objects = ActivityManager()

    def __str__(self):
        return self.name.name

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Activity Annotations"

    def get_activities_group_by_category(category):
        category = ActivityType.objects.filter(category=category)
        return (
            Activity.objects.filter(name_id__in=category)
            .annotate(activity=F("name__name"))
            .values("activity")
            .annotate(total=Count(1))
        )


# Used to keep track of time annotations were made for volunteer engagement metrics
class AnnotationCounter(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    annotation_type = models.CharField(
        max_length=10,
        choices=[("category", "category"), ("species", "species"), ("activity", "activity")],
    )
    annotator = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="recent_annotations")
    annotation_count = models.IntegerField()
    image_count = models.IntegerField()
