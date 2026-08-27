# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.db.models import F
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Image, Upload
from locations.models import CameraStation, MacroSite


def update_cached_image_counts(upload_id, total_delta=0, processed_delta=0):
    upload = Upload.objects.select_related("camera_station__micro_site__macro_site").get(id=upload_id)

    if total_delta or processed_delta:
        Upload.objects.filter(id=upload_id).update(
            img_count=F("img_count") + total_delta,
            processed_img_count=F("processed_img_count") + processed_delta,
        )
        CameraStation.objects.filter(id=upload.camera_station_id).update(
            total_img_count=F("total_img_count") + total_delta,
            processed_img_count=F("processed_img_count") + processed_delta,
        )
        MacroSite.objects.filter(id=upload.camera_station.micro_site.macro_site_id).update(
            total_img_count=F("total_img_count") + total_delta,
            processed_img_count=F("processed_img_count") + processed_delta,
        )


@receiver(pre_save, sender=Image)
def cache_old_image_values(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = Image.objects.filter(pk=instance.pk).values("upload_id", "processed").first()
    if previous:
        instance._old_upload_id = previous["upload_id"]
        instance._old_processed = previous["processed"]


@receiver(post_save, sender=Image)
def sync_cached_counts_on_image_save(sender, instance, created, **kwargs):
    if created:
        update_cached_image_counts(
            instance.upload_id,
            total_delta=1,
            processed_delta=1 if instance.processed else 0,
        )
        return

    old_upload_id = getattr(instance, "_old_upload_id", instance.upload_id)
    old_processed = getattr(instance, "_old_processed", instance.processed)

    if old_upload_id != instance.upload_id:
        update_cached_image_counts(
            old_upload_id,
            total_delta=-1,
            processed_delta=-1 if old_processed else 0,
        )
        update_cached_image_counts(
            instance.upload_id,
            total_delta=1,
            processed_delta=1 if instance.processed else 0,
        )
        return

    if old_processed != instance.processed:
        update_cached_image_counts(
            instance.upload_id,
            processed_delta=1 if instance.processed else -1,
        )


@receiver(post_delete, sender=Image)
def sync_cached_counts_on_image_delete(sender, instance, **kwargs):
    update_cached_image_counts(
        instance.upload_id,
        total_delta=-1,
        processed_delta=-1 if instance.processed else 0,
    )


@receiver(post_save, sender=Upload)
def sync_image_fields_with_upload(sender, instance, **kwargs):
    images = instance.images.all()

    images.update(deleted=instance.deleted)
