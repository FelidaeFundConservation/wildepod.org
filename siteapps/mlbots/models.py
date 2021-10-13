from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
from uploads.models import Image


# Type of tasks the bot can do Ex: "Object detection", "Species identification"
class BotTaskType(TimeStampedModel):

    name = models.CharField(max_length=100, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("created",)


# Meta information about specific bots - These are specific trained ML models
class Bot(TimeStampedModel):
    # The file name & the type of task it does
    name = models.CharField(max_length=100, unique=True)
    task_type = models.ForeignKey(BotTaskType, on_delete=models.PROTECT)
    # Version id for the specific model
    version = models.CharField(max_length=100)

    # The format the model is saved in
    model_format = models.CharField(
        max_length=10,
        choices=[
            (".pth", "PyTorch"),
            (".pb", "TensorFlow"),
        ],
    )

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("created",)
