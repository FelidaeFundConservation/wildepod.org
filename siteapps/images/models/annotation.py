import uuid

from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .image import Annotator, Image

NUM_ACCEPTS_OVER_REJECTS = 2
MIN_MEGADETECTOR_CONFIDENCE = 0.25


# Bounding Box manager. For now, this simply returns "valid" bounding boxes as determined
# by the accept/reject ratio
class BoundingBoxManager(models.Manager):
    def with_counts(self):
        return self.annotate(
            num_accepted=models.functions.Coalesce(models.Count("accepted_by"), 0),
            num_rejected=models.functions.Coalesce(models.Count("rejected_by"), 0),
        )

    # TODO: Compute this as a posterior probability with the confidence as the prior (if it exists
    def with_effective_confidence(self):
        pass

    def valid(self):
        return (
            self.annotate(
                num_accepted=models.functions.Coalesce(models.Count("accepted_by"), 0),
                num_rejected=models.functions.Coalesce(models.Count("rejected_by"), 0),
            )
            .filter(confidence__gte=MIN_MEGADETECTOR_CONFIDENCE)
            .filter(num_accepted__lte=models.F("num_rejected") + NUM_ACCEPTS_OVER_REJECTS)
        )


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


# Generic tag manager. For now, this simply returns "valid" as determined
# by the accept/reject ratio. It also prioritizes annotations based on confidence
class CategoryManager(models.Manager):
    def with_counts(self):
        return self.annotate(
            num_accepted=models.functions.Coalesce(models.Count("accepted_by"), 0),
            num_rejected=models.functions.Coalesce(models.Count("rejected_by"), 0),
        )

    # TODO: Compute this as a posterior probability with the confidence as the prior (if it exists
    def with_effective_confidence(self):
        pass

    # A valid category is one that passes the accept/reject ratio threshold and
    # returns the most recently updated category
    def valid(self):
        return (
            self.annotate(
                num_accepted=models.functions.Coalesce(models.Count("accepted_by"), 0),
                num_rejected=models.functions.Coalesce(models.Count("rejected_by"), 0),
            )
            .filter(num_accepted__lte=models.F("num_rejected") + NUM_ACCEPTS_OVER_REJECTS)
            .order_by("-confidence", "-created", "-modified")
        )


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
