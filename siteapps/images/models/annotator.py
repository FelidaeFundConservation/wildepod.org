from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# Meta information about specific bots - These are specific trained ML models
class Bot(TimeStampedModel):
    # The name of the bot & its version
    name = models.CharField(max_length=250)
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

    # Model API - This is the url where the model is hosted
    # In the first version, this was a cloud function. Moving forward, they will be cloud run urls
    # The cloud run urls are not public which means a token needs to be obtained before calling this
    model_api_url = models.URLField(max_length=1000, blank=True, null=True)

    # This calls the model set with this detection threshold
    threshold = models.FloatField(default=0.05)

    # NOTE: This field will be deprecated since models will be stored directly in the cloud run container
    # to prevent model download at every container start
    # Model location - This is the actual model file that the API loads
    # Cloud functions might have default models loaded
    # Since the location can be a gs:// url, we need to store it as a string
    model_file_url = models.CharField(max_length=1000, blank=True, null=True)

    def __str__(self):
        return f"{self.name}: {self.version}"

    class Meta:
        unique_together = [["name", "version"]]
        ordering = ("created",)


# An annotator is an abstraction over an ML model and a signed in user
class Annotator(TimeStampedModel):
    # Type of the annotator. Either a human or a bot
    type = models.CharField(max_length=10, choices=[("human", "Human"), ("bot", "Bot")])
    # Fields to save an ML model or a user
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT, blank=True, null=True)
    human = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True)

    # The annotator's annotation count on volunteer engagement page current up to this date
    engagement_info_last_update = models.DateTimeField(blank=True, null=True)

    # Last saved totals
    total_category_annotations = models.IntegerField(null=True)
    total_species_annotations = models.IntegerField(null=True)
    total_activity_annotations = models.IntegerField(null=True)

    # Preferences
    prioritize_tagging_animals = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        if self.type == "human":
            return self.human.name
        elif self.type == "bot":
            return self.bot.name
        else:
            return ""

    class Meta:
        ordering = ("created",)
