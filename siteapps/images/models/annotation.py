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
    Base Manager to annotate objects with certainty
    """

    def annotated(self):
        # Combining multiple aggregations with annotate() will yield the wrong results because joins are used instead of subqueries
        # https://docs.djangoproject.com/en/4.0/topics/db/aggregation/#combining-multiple-aggregations
        return self.annotate(
            confidence_threshold=Case(
                When(created_by__type="bot", then="created_by__bot__threshold"),
                default=0.0,
            ),
            keep=ExpressionWrapper(Q(confidence__gte=F("confidence_threshold")), output_field=models.BooleanField()),
            num_accepted=Coalesce(Count("accepted_by", distinct=True), 0),
            num_rejected=Coalesce(Count("rejected_by", distinct=True), 0),
            vote_diff=F("num_accepted") - F("num_rejected"),
            voted_valid=ExpressionWrapper(
                Q(vote_diff__gte=settings.NUM_ACCEPTS_OVER_REJECTS),
                output_field=models.BooleanField(),
            ),
            voted_invalid=ExpressionWrapper(
                Q(vote_diff__lte=-settings.NUM_ACCEPTS_OVER_REJECTS), output_field=models.BooleanField()
            ),
            vote_uncertain=ExpressionWrapper(
                Q(vote_diff__lt=settings.NUM_ACCEPTS_OVER_REJECTS)
                & Q(vote_diff__gt=-settings.NUM_ACCEPTS_OVER_REJECTS),
                output_field=models.BooleanField(),
            ),
            is_staff_vote=ExpressionWrapper(
                Exists(
                    BoundingBox.objects.filter(
                        Exists(
                            Annotator.objects.filter(
                                Q(human__is_staff=True) | Q(human__is_expert=True), accepted_annotation=OuterRef("pk")
                            )
                        ),
                        image=OuterRef("image"),
                    )
                ),
                output_field=models.BooleanField(),
            ),
        )

    def uncertain(self):
        return self.annotated().filter(Q(vote_uncertain=True) & Q(is_staff_vote=False), keep=True)

    def valid(self):
        return self.annotated().filter(Q(voted_valid=True) | Q(is_staff_vote=True), keep=True)

    def valid_or_uncertain(self):
        return self.annotated().filter(Q(voted_valid=True) | Q(vote_uncertain=True), keep=True)


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
    # Override the default methods
    def valid(self):
        return super().valid().order_by("-vote_diff", "-confidence", "-created", "-modified")

    def valid_or_uncertain(self):
        return super().valid_or_uncertain().order_by("-vote_diff", "-confidence", "-created", "-modified")


# Certainty annotations for activites
class ActivityManager(BaseAnnotationManager):
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

    # Bounding box validity
    validity = models.CharField(
        "Validity",
        max_length=250,
        choices=(
            ("INVALID", "Invalid"),
            ("UNCERTAIN", "Uncertain"),
            ("VALID", "Valid"),
        ),
        null=True,
        default=None,
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

    objects = CategoryManager()

    def __str__(self):
        return self.name.name

    class Meta:
        ordering = ("-modified",)
        verbose_name_plural = "Species Annotations"

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
