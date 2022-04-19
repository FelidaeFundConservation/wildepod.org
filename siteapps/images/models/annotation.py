import uuid

from django.db import models
from django.db.models import Count, ExpressionWrapper, Q
from django.db.models.functions import Coalesce
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .image import Annotator, Image

NUM_ACCEPTS_OVER_REJECTS = 2
MIN_MEGADETECTOR_CONFIDENCE = 0.25


class BaseAnnotationManager(models.Manager):
    """
    Base Manager to annotate objects with certainty
    """

    def annotated(self):
        # Combining multiple aggregations with annotate() will yield the wrong results because joins are used instead of subqueries
        # https://docs.djangoproject.com/en/4.0/topics/db/aggregation/#combining-multiple-aggregations
        return self.annotate(
            keep=ExpressionWrapper(Q(confidence__gte=MIN_MEGADETECTOR_CONFIDENCE), output_field=models.BooleanField()),
            num_accepted=Coalesce(Count("accepted_by", distinct=True), 0),
            num_rejected=Coalesce(Count("rejected_by", distinct=True), 0),
            vote_diff=models.F("num_accepted") - models.F("num_rejected"),
            voted_valid=ExpressionWrapper(
                Q(vote_diff__gte=NUM_ACCEPTS_OVER_REJECTS), output_field=models.BooleanField()
            ),
            voted_invalid=ExpressionWrapper(
                Q(vote_diff__lte=-NUM_ACCEPTS_OVER_REJECTS), output_field=models.BooleanField()
            ),
            vote_uncertain=ExpressionWrapper(
                Q(vote_diff__lt=NUM_ACCEPTS_OVER_REJECTS) & Q(vote_diff__gt=-NUM_ACCEPTS_OVER_REJECTS),
                output_field=models.BooleanField(),
            ),
        )

    def uncertain(self):
        return self.annotated().filter(keep=True).filter(vote_uncertain=True)

    def valid(self):
        return self.annotated().filter(keep=True).filter(voted_valid=True)

    def valid_or_uncertain(self):
        return self.annotated().filter(keep=True).filter(Q(voted_valid=True) | Q(vote_uncertain=True))


# Certainty annotations for bounding boxes
class BoundingBoxManager(BaseAnnotationManager):
    pass


# Certainty annotations for categories
class CategoryManager(BaseAnnotationManager):
    # Override the default methods
    def valid(self):
        return super().valid().order_by("-vote_diff", "-confidence", "-created", "-modified")

    def valid_or_uncertain(self):
        return super().valid_or_uncertain().order_by("-vote_diff", "-confidence", "-created", "-modified")


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

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_annotation", blank=True)

    objects = BoundingBoxManager()

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return (
            f"{self.image.upload.camera_station.micro_site.macro_site.name} |"
            f" {self.image.upload.camera_station.micro_site.name} | {self.id}"
        )

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Bounding Boxes"


# Model to maintain different species types
class SpeciesName(TimeStampedModel):
    name = models.CharField(max_length=250, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Species Names"


# TODO: Combine category & species into a single base model & inherit from it
# Each annotation is futher linked to an Annotation Type if the primary class is an animal
# This is the Species of the animal identified
class Category(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.CASCADE)

    # The main category of the detected object. This can be "Animal", "Human" or "Vehicle"
    name = models.CharField(
        max_length=10,
        choices=[("animal", "animal"), ("vehicle", "vehicle"), ("person", "person")],
    )

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_category_annotation")

    # This, if created by Megadetector, is the same confidence as the bounding box
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_category_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_category_annotation", blank=True)

    objects = CategoryManager()

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.id} | {self.name} | BBox: {self.bounding_box.id}"

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Category Annotations"


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

    objects = CategoryManager()

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name.name

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Species Annotations"
