from django.contrib.auth.models import AbstractUser
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# Model to extend django user model to have additional profile fields
class Profile(AbstractUser, TimeStampedModel):
    phone_number = models.CharField("Phone Number", max_length=25, blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.username}"

    class Meta:
        ordering = ("username",)
