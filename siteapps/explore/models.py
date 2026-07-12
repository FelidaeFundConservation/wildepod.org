# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings
from django.db import models
from locations.models import MacroSite
from model_utils.models import TimeStampedModel


class Snapshot(TimeStampedModel):
    # Volunteer/Staff that requested the data export
    volunteer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    # Filters
    start_date = models.DateField("Start Date", blank=True, null=True)
    end_date = models.DateField("End Date", blank=True, null=True)
    # Optional macrosite filter
    macrosites = models.ManyToManyField(MacroSite, blank=True)
    # Classes on image annotations
    # annotated_only = models.BooleanField("Annotated Only", default=False)
    # Archive file with a bunch of csvs & the place where it is stored
    data = models.FileField(upload_to="data/snapshots/", blank=True, null=True)

    # Snapshot status. By default, it is pending on create
    status = models.CharField(
        max_length=10, choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")], default="pending"
    )

    def __str__(self):
        return f"{self.volunteer.name}-{self.created}"

    class Meta:
        ordering = ("created",)
