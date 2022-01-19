import uuid

from django.conf import settings
from django.db import models
from locations.models import CameraStation
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .image import Image


# Meta information about specific bots - These are specific trained ML models
class Bot(TimeStampedModel):
    # The name of the bot & its version
    name = models.CharField(max_length=250, unique=True)
    version = models.CharField(max_length=10)

    # The type of the task. Either "Object detection" or "Object identification"
    task_type = models.CharField(
        max_length=100,
        choices=[("object_detection", "Object Detection"), ("object_identification", "Object Identification")],
        blank=True,
        null=True,
    )

    # Model API - This is the cloud function that might be called to make the prediction
    model_api_url = models.URLField(max_length=1000, blank=True, null=True)
    # Model location - This is the actual model file that the API loads
    # Cloud functions might have default models loaded
    model_file_url = models.URLField(max_length=1000, blank=True, null=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name + " " + self.version

    class Meta:
        ordering = ("created",)


# An annotator is an abstraction over an ML model and a signed in user
class Annotator(TimeStampedModel):
    # Type of the annotator. Either a human or a bot
    type = models.CharField(max_length=10, choices=[("human", "Human"), ("bot", "Bot")])
    # Fields to save an ML model or a user
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT, blank=True, null=True)
    human = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        if self.type == "human":
            return self.human.username
        else:
            return self.bot.name

    class Meta:
        ordering = ("created",)


# Each annotation is a bounding box linked to an image
# Bounding boxes are identified by x,y,w,h where w,h are normalized width & height
# Each annotation has a creator that is either an ML model or a human
# Each annotation can be accepted/rejected by a human
# Each annotation has a primary class from MegaDetector i.e one of 'Animal', 'Human', 'Vehicle'
# and a secondary class that identifies the species
class BoundingBox(TimeStampedModel):
    # A unique identifier for the annotation
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The image the annotation is linked to
    image = models.ForeignKey(Image, on_delete=models.PROTECT)

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


# Each annotation is futher linked to an Annotation Type if the primary class is an animal
# This is the Species of the animal identified
class Category(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.PROTECT)

    # The main category of the detected object. This can be "Animal", "Human" or "Vehicle"
    name = models.CharField(max_length=10, choices=[("animal", "animal"), ("vehicle", "vehicle"), ("human", "human")])

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_category_annotation")

    # This, if created by Megadetector, is the same confidence as the bounding box
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_category_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_category_annotation", blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.id} | {self.name} | BBox: {self.bounding_box.id}"

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Categories"


# Model to maintain different species types
class SpeciesName(TimeStampedModel):
    name = models.CharField(max_length=250, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("created",)
        verbose_name_plural = "Species Names"


# Each annotation is futher linked to an Annotation Type if the primary class is an animal
# This is the Species of the animal identified
class Species(TimeStampedModel):
    # UUID identifier
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The bounding box this category annotation is linked to
    bounding_box = models.ForeignKey(BoundingBox, on_delete=models.PROTECT)

    # The species of the animal
    name = models.ForeignKey(SpeciesName, on_delete=models.PROTECT)

    # The creator of the annotation
    created_by = models.ForeignKey(Annotator, on_delete=models.PROTECT, related_name="created_species_annotation")

    # Confidence from the species detection model
    confidence = models.FloatField(default=1.0)

    # List of accept/rejects for this annotation
    accepted_by = models.ManyToManyField(Annotator, related_name="accepted_species_annotation", blank=True)
    rejected_by = models.ManyToManyField(Annotator, related_name="rejected_species_annotation", blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name.name

    class Meta:
        ordering = ("-created",)
        verbose_name_plural = "Species"
