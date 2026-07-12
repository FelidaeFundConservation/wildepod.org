# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings
from django.db import models
from inventory.models import Camera, Padlock, PythonLock
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# --- Model for different areas, counties, macro & micro sites and grids ---
class Area(TimeStampedModel):
    name = models.CharField("Area name", max_length=250, unique=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class County(TimeStampedModel):
    name = models.CharField("County name", max_length=250, unique=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Counties"


class MacroSite(TimeStampedModel):
    name = models.CharField("Macro-site name", max_length=250, unique=True)
    county = models.ForeignKey(County, on_delete=models.PROTECT)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)

        # Keep commented while testing to check effect on performance
        # indexes = [
        #     models.Index(fields=['name',])
        # ]


class Grid(TimeStampedModel):
    name = models.CharField("Grid name", max_length=250, unique=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class MicroSite(TimeStampedModel):
    name = models.CharField("Micro-site name", max_length=250, unique=True)
    macro_site = models.ForeignKey(MacroSite, on_delete=models.PROTECT)
    grid = models.ForeignKey(Grid, on_delete=models.SET_NULL, verbose_name="Grid name", null=True, blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)

        indexes = [
            models.Index(fields=['macro_site', 'name'], name='idx_microsite_macro_name'),
        ]


class TrailType(TimeStampedModel):
    name = models.CharField("Trail Type", max_length=100, unique=True)
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class TrailSurfaceType(TimeStampedModel):
    name = models.CharField("Trail Surface Type", max_length=100, unique=True)
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class LandUseType(TimeStampedModel):
    name = models.CharField("Land Use Type", max_length=100, unique=True)
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class HabitatType(TimeStampedModel):
    name = models.CharField("Habitat type", max_length=100, unique=True)
    comments = models.TextField("Additional notes", blank=True)
    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


# The main camera station model that all images are linked to
class CameraStation(TimeStampedModel):
    # A camera station is anchored around lat/long and a semantically created (optionally generated) id
    station_id = models.CharField("Camera Station ID", max_length=100, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    # Optional elevation information
    elevation = models.IntegerField(null=True, blank=True)
    elevation_unit = models.CharField(
        "What unit is the elevation number in?",
        choices=[("ft", "feet"), ("m", "meters")],
        default="m",
        max_length=10,
        null=True,
        blank=True,
    )

    # Meta information about the the camera station site
    micro_site = models.ForeignKey(MicroSite, on_delete=models.PROTECT)

    trail_type = models.ForeignKey(TrailType, on_delete=models.PROTECT, null=True, blank=True)

    trail_surface = models.ForeignKey(
        TrailSurfaceType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    land_use_type = models.ManyToManyField(LandUseType, blank=True)

    habitat_types = models.ManyToManyField(
        HabitatType,
        blank=True,
    )

    habitat_notes = models.TextField("Additional habitat notes", blank=True)

    # Optionally linked camera from the existing inventory
    camera = models.OneToOneField(
        Camera,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Felidae camera serial number (if applicable)",
    )
    external_camera = models.CharField(
        "External camera identifier (if not a felidae camera)",
        null=True,
        blank=True,
        max_length=250,
    )

    # Meta information about camera station status
    date_deployed = models.DateField()
    date_last_checked = models.DateField("Date the camera station was last checked", null=True, blank=True)
    date_to_be_checked = models.DateField("Date the camera station should be checked next", null=True, blank=True)
    date_taken_down = models.DateField("Date the camera station was decommissioned", null=True, blank=True)

    # Camera box & Lock information
    boxed = models.BooleanField(null=True, blank=True, verbose_name="Is it in a box?")
    padlock = models.ForeignKey(
        Padlock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Padlock type (if applicable)",
    )
    python_lock = models.OneToOneField(
        PythonLock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Python lock (if applicable)",
    )

    # Volunteer assigned to the camera station
    volunteer = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True)

    # Additional free text comments about the specific camera station
    comments = models.TextField("Instructions/Comments", blank=True)

    def __str__(self):
        return (
            f"{self.station_id} ({self.latitude}, {self.longitude}) | {self.micro_site} |"
            f" {self.micro_site.macro_site.name}"
        )

    class Meta:
        ordering = ("station_id",)

        indexes = [
            models.Index(fields=['micro_site', 'station_id', 'latitude', 'longitude'], name='idx_camerastation_grouping'),
        ]
