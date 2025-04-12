from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Image, Upload


@receiver(post_save, sender=Image)
def increment_img_count(sender, instance, created, **kwargs):
    if created:
        Upload.objects.filter(id=instance.upload.id).update(img_count=F("img_count") + 1)


@receiver(post_delete, sender=Image)
def decrement_img_count(sender, instance, **kwargs):
    Upload.objects.filter(id=instance.upload.id).update(img_count=F("img_count") - 1)
