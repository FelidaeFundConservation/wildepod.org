from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


# Model to hold the entire content for Help in markdown
class Instructions(TimeStampedModel):
    version = models.CharField("Version Name", max_length=250, unique=True)
    content = RichTextUploadingField("User Guide/Instructions")
    active = models.BooleanField("Active", default=True)

    # History of model instance changes
    history = HistoricalRecords()

    def __str__(self):
        return self.content[:100]

    def save(self, *args, **kwargs):
        if self.active:
            Instructions.objects.filter(active=True).update(active=False)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ("pk",)
        verbose_name_plural = "Instructions"
