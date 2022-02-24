from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .managers import UserManager


# Model to extend django user model to have additional profile fields
class User(AbstractUser, TimeStampedModel):
    # User model only needs email and password. No username is needed.
    username = None
    email = models.EmailField(_("email address"), unique=True)

    #: Keep only a name field instead of first & last names
    name = models.CharField(_("Name"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore

    # Additional flag to indicate if user is a volunteer
    is_volunteer = models.BooleanField(default=False)
    # Phone number if needed
    phone_number = models.CharField("Phone Number", max_length=25, blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        ordering = ("name", "email")
