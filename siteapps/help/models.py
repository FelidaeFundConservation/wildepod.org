from django.core import validators
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

# # Model to hold the entire content for Help in markdown
# class HelpPage(TimeStampedModel):
#     pk = models.CharField("Primary key", default="help", )
#     content = models.TextField("Help Page in markdown")

#     # History of model instance changes
#     history = HistoricalRecords()

#     def __str__(self):
#         return self.content[:100]

#     class Meta:
#         ordering = ("pk",)
