from django.core import validators
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# Model for different padlock types
class Padlock(TimeStampedModel):
    name = models.CharField("Padlock type", max_length=250, unique=True)
    count = models.IntegerField(verbose_name="Number of units", default=1)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


# Model for different python locks
class PythonLock(TimeStampedModel):
    # Python lock number and if it has a duplicate key
    number = models.CharField("Python Lock number", max_length=25, unique=True)
    duplicate_key_exists = models.BooleanField("Is there a duplicate key?", default=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.number

    class Meta:
        ordering = ("number",)


# Model to track different camera box models
class Box(TimeStampedModel):
    name = models.CharField("Box model", max_length=250, unique=True)
    count = models.IntegerField(verbose_name="Number of empty units")
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Boxes"


# Model for camera brands
class CameraBrand(TimeStampedModel):
    name = models.CharField("Brand Name", max_length=250, unique=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


# Model for different camera models
class CameraModel(TimeStampedModel):
    # Model number, name & brand
    number = models.CharField("Model number", max_length=250, unique=True, null=True, blank=True)
    name = models.CharField("Model name", max_length=250, null=True, blank=True)
    brand = models.ForeignKey(CameraBrand, on_delete=models.PROTECT)

    # Meta information about the model. Power source & number of batteries
    POWER_SOURCE_CHOICES = [("battery", "battery"), ("solar", "solar")]
    power_source = models.CharField(choices=POWER_SOURCE_CHOICES, max_length=25)
    num_batteries = models.IntegerField("Number of batteries", null=True, blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.brand.name}: {self.name}"

    class Meta:
        ordering = ("name",)


# Model to house metadata for specific physical camera units
class Camera(TimeStampedModel):
    # Each model must have a serial number or some unique identifier used to physically tag the camera
    serial_number = models.CharField(max_length=250, unique=True)
    # Linked camera model type
    model = models.ForeignKey(CameraModel, on_delete=models.PROTECT)
    # Status of the camera
    CAMERA_STATUS_CHOICES = [
        ("deployed", "Deployed"),
        ("ready_to_deploy", "Ready to deploy"),
        ("needs_refurbishment", "Needs refurbishment"),
        ("stolen", "Stolen"),
    ]
    status = models.CharField("Camera Status", choices=CAMERA_STATUS_CHOICES, max_length=50)
    # Current battery level if camera in use
    battery_level = models.IntegerField(
        "Battery level",
        validators=[validators.MinValueValidator(0), validators.MaxValueValidator(100)],
        null=True,
        blank=True,
    )
    # Additional free text comments about the specific camera
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.serial_number} - {self.model.brand.name}: {self.model.name}"

    class Meta:
        ordering = ("serial_number",)
