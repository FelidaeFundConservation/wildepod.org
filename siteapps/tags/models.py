from django.conf import settings
from django.db import models
from mlbots.models import Bot
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
from uploads.models import Image


# Model to maintain different species tags
class SpeciesTag(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("created",)


# Models to track different ML generated tags
class BlankTagByBot(TimeStampedModel):
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT)
    blank = models.BooleanField("Blank Image?")
    score = models.FloatField()

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.image.filename} | {self.bot.name} | Blank - {self.blank} | Score - {self.score}"

    class Meta:
        ordering = ("created",)


class SpeciesTagByBot(TimeStampedModel):
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT)
    species = models.ForeignKey(SpeciesTag, on_delete=models.CASCADE)
    score = models.FloatField()

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.image.filename} | {self.bot.name} | Species - {self.species} | Score - {self.score}"

    class Meta:
        ordering = ("created",)


# Model to add different human annotated tags to images
class BlankTagByHuman(TimeStampedModel):
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    human = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    blank = models.BooleanField("Blank Image?")

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.image.filename} | {self.human.username} | Blank - {self.blank}"

    class Meta:
        ordering = ("created",)


class SpeciesTagByHuman(TimeStampedModel):
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    human = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    species = models.ForeignKey(SpeciesTag, on_delete=models.CASCADE)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.image.filename} | {self.human.username} | Species - {self.species}"

    class Meta:
        ordering = ("created",)
