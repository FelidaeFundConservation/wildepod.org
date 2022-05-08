from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# Meta information about specific bots - These are specific trained ML models
class Bot(TimeStampedModel):
    # The name of the bot & its version
    name = models.CharField(max_length=250, unique=True)
    version = models.CharField(max_length=10)

    # The type of the task. Either "Object detection" or "Object identification"
    task_type = models.CharField(
        max_length=100,
        choices=[
            ("object_detection", "Object Detection"),
            ("object_identification", "Object Identification"),
        ],
        blank=True,
        null=True,
    )

    # Model API - This is the cloud function that might be called to make the prediction
    model_api_url = models.URLField(max_length=1000, blank=True, null=True)
    # Model location - This is the actual model file that the API loads
    # Cloud functions might have default models loaded
    model_file_url = models.URLField(max_length=1000, blank=True, null=True)

    def __str__(self):
        return f"{self.name}: {self.version}"

    class Meta:
        ordering = ("created",)


# An annotator is an abstraction over an ML model and a signed in user
class Annotator(TimeStampedModel):
    # Type of the annotator. Either a human or a bot
    type = models.CharField(max_length=10, choices=[("human", "Human"), ("bot", "Bot")])
    # Fields to save an ML model or a user
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT, blank=True, null=True)
    human = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True)

    def __str__(self):
        if self.type == "human":
            return self.human.name
        else:
            return self.bot.name

    class Meta:
        ordering = ("created",)
