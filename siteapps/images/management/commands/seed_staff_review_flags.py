# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Seeds local images with a spread of staff-review / reported / social flags.

Local development only. Gives the Search Images "Flags" column something to render:
every flag reason, auto-flags, reported images, social votes, and plain images to
contrast against. Re-running resets all flags first, so it is safe to repeat.

    python manage.py seed_staff_review_flags
"""

import datetime
import random

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from images.models import Annotator, BoundingBox, Image, StaffReviewFlagReason, StaffReviewFlagSource, Upload

TARGET_IMAGE_COUNT = 40
THUMBNAIL_COUNT = 40

# (reason, how many). None means an automatic flag, which carries no reason.
FLAG_SPREAD = [
    (StaffReviewFlagReason.SPECIES_ID, 8),
    (StaffReviewFlagReason.BBOX_PROTOCOL, 5),
    (StaffReviewFlagReason.OTHER, 2),
    (None, 5),
]
OTHER_DETAILS = ["Two cameras triggered at once", "Timestamp looks wrong"]


class Command(BaseCommand):
    help = "Seed local images with staff-review, reported and social-media flags."

    def handle(self, *args, **options):
        rng = random.Random(20260819)

        uploads = list(Upload.objects.all())
        if not uploads:
            raise CommandError("No uploads in the database -- seed base data first.")

        self._top_up_images(uploads, rng)
        self._make_annotatable(rng)

        images = list(Image.objects.order_by("dropbox_file_name"))
        # Reset through the model's own definition of "not flagged", so a re-run cannot leave
        # the per-pipeline review flags set while the global one says the image is clear.
        Image.objects.update(**Image.CLEARED_STAFF_REVIEW_FIELDS)
        Image.objects.update(flagged_by=None, flagged_at=None, image_reported=False, social_media_worthy=0)

        volunteers = list(Annotator.objects.filter(type="human", human__is_staff=False))
        cursor = self._apply_flags(images, volunteers, rng)
        cursor = self._apply_reported(images, cursor)
        self._apply_social(images, cursor, rng)
        self._apply_skips(images, volunteers, rng)

        self.stdout.write(
            self.style.SUCCESS(
                f"{Image.objects.count()} images: "
                f"{Image.objects.filter(staff_review_needed=True).count()} flagged, "
                f"{Image.objects.filter(image_reported=True).count()} reported, "
                f"{Image.objects.filter(social_media_worthy__gt=0).count()} social."
            )
        )

    def _top_up_images(self, uploads, rng):
        """Creates images up to TARGET_IMAGE_COUNT, reusing the seeded thumbnails on disk."""
        existing = Image.objects.count()
        now = timezone.now()

        for index in range(existing, TARGET_IMAGE_COUNT):
            Image.objects.create(
                upload=uploads[index % len(uploads)],
                dropbox_file_name=f"IMG_{index:04d}.jpg",
                dropbox_file_path=f"/seed/IMG_{index:04d}.jpg",
                dropbox_file_path_display=f"/seed/IMG_{index:04d}.jpg",
                dropbox_content_hash=f"seedhash{index:04d}",
                dropbox_file_id=f"id:seed{index}",
                file_size=rng.randint(100_000, 5_000_000),
                trigger_timestamp=now - datetime.timedelta(days=rng.randint(1, 45), hours=rng.randint(0, 23)),
                thumbnail_gcloud_path=f"thumbnails/seed_{index % THUMBNAIL_COUNT:04d}.jpg",
                processed=True,
                use_precomputed_flags=True,
                has_bbox_above_confidence_threshold=True,
            )

        created = TARGET_IMAGE_COUNT - existing
        if created > 0:
            self.stdout.write(f"Created {created} image(s).")

    def _make_annotatable(self, rng):
        """Gives every image what the annotation queues require, so Classify has work to show.

        species_pipeline_query() only serves images that MegaDetector found something in and
        that still have an unresolved box, so without this the queues render "no more images"
        no matter how many rows exist.
        """
        bot, _ = Annotator.objects.get_or_create(type="bot", defaults={"human": None})

        Image.objects.update(
            processed=True,
            use_precomputed_flags=True,
            has_bbox_above_confidence_threshold=True,
            has_uncertain_bbox=True,
            has_animals=True,
            has_wild_animals=True,
            species_pipeline_complete=False,
            activity_pipeline_complete=False,
            species_ai_detections="['Mule deer']",
        )

        for image in Image.objects.filter(boundingbox__isnull=True):
            BoundingBox.objects.create(
                image=image,
                x=rng.uniform(0.1, 0.6),
                y=rng.uniform(0.1, 0.6),
                w=rng.uniform(0.15, 0.3),
                h=rng.uniform(0.15, 0.3),
                confidence=rng.uniform(0.6, 0.99),
                created_by=bot,
            )

    def _apply_flags(self, images, volunteers, rng):
        """Flags a slice of images per FLAG_SPREAD. Returns the index it stopped at."""
        cursor = 0
        details = iter(OTHER_DETAILS * 5)

        for reason, count in FLAG_SPREAD:
            for image in images[cursor : cursor + count]:
                if reason is None:
                    image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)
                    continue

                image.flag_for_staff_review(
                    source=StaffReviewFlagSource.MANUAL,
                    annotator=rng.choice(volunteers) if volunteers else None,
                    reason=reason,
                    reason_detail=next(details) if reason == StaffReviewFlagReason.OTHER else "",
                )
            cursor += count

        return cursor

    def _apply_reported(self, images, cursor):
        """Reports 4 images -- 2 that are also flagged, so overlapping badges show up."""
        reported = images[:2] + images[cursor : cursor + 2]
        Image.objects.filter(id__in=[image.id for image in reported]).update(image_reported=True)

        return cursor + 2

    def _apply_social(self, images, cursor, rng):
        for image in images[cursor : cursor + 6]:
            Image.objects.filter(id=image.id).update(social_media_worthy=rng.randint(1, 5))

    def _apply_skips(self, images, volunteers, rng):
        """Skips a third of the images, weighted so the auto-flagged ones are the worst offenders."""
        if not volunteers:
            return

        for image in images:
            image.species_skipped_by.clear()
            image.bbox_skipped_by.clear()

        auto_flagged = [i for i in images if i.flag_source == StaffReviewFlagSource.AUTO_SKIPS]

        for image in auto_flagged:
            # Over AUTO_REVIEW_FLAG_THRESHOLD, which is what tripped the auto-flag
            image.species_skipped_by.add(*rng.sample(volunteers, min(3, len(volunteers))))

        for image in rng.sample(images, len(images) // 3):
            if image in auto_flagged:
                continue
            image.species_skipped_by.add(*rng.sample(volunteers, min(rng.randint(1, 2), len(volunteers))))
