# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from .managers import UserManager


# Model to extend django user model to have additional profile fields
class User(AbstractUser, TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # User model only needs email and password. No username is needed.
    username = None
    email = models.EmailField("email address", unique=True)

    #: Keep only a name field instead of first & last names
    name = models.CharField("Name", blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore

    # Additional flag to indicate if user is a volunteer
    is_volunteer = models.BooleanField(default=False)
    # Flag to indicate an expert user. Their votes will provide direct validation for category, species and activity
    # (i.e. no consensus necessary)
    is_expert = models.BooleanField(
        default=False,
        help_text="Expert user votes directly validate Category, Species and Activity without need for additional consensus",
    )
    # Phone number if needed
    phone_number = models.CharField("Phone Number", max_length=25, blank=True)

    # When this user last worked the staff review queue, used to mark newly arrived images as
    # NEW. Two timestamps rather than one: overwriting a single field on arrival would clear
    # every badge the moment the page loaded, before anything had been looked at.
    #
    # last_review_visit_at moves to "now" when a review session starts, and
    # previous_review_visit_at keeps the start of the session before it. NEW means "flagged
    # since the last time I sat down with this queue", so it is the older of the two that the
    # badge compares against, and it holds still for the whole session.
    #
    # Both are None for a user who has never opened the queue, which shows no badges at all.
    # That is deliberate: on a first visit every image is equally unseen, so badging the lot
    # would say nothing.
    last_review_visit_at = models.DateTimeField(null=True, blank=True)
    previous_review_visit_at = models.DateTimeField(null=True, blank=True)

    # History of model instance changes
    history = HistoricalRecords()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        ordering = ("name", "email")
