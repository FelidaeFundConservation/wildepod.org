from django.conf import settings
from django.db import models
from inventory.models import Camera, Padlock, PythonLock
from model_utils.models import TimeStampedModel

# # Model to track exports, creators & its link
# class Export(TimeStampedModel):
#     # UUID for the upload
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     # Volunteer/Staff that requested the data export
#     volunteer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
#     # Export time
#     datetime = models.DateTimeField("Export Creation Time")

#     def __str__(self):
#         return f"{self.datetime}-{self.id}"

#     class Meta:
#         ordering = ("-datetime",)
