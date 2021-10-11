from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
from uploads.models import Image


# Model to save all human annotations across images in the database
class Tag(TimeStampedModel):
    annotator = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    image = models.OneToOneField(Image, on_delete=models.CASCADE)

    def __str__(self):
        return self.image.image_id

    class Meta:
        ordering = ("created",)
