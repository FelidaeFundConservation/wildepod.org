# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Backlog auto-approval of single high-confidence human images.

Retroactively completes already-uploaded images that contain exactly one bounding box
classified as a high-confidence person, so they leave the species (and human-behavior)
annotation queues without ever being served to a human annotator. Each approval reuses the
same service-account voting routine as the forward (upload-time) path, so an auto-annotated
image carries the identical audit trail regardless of which path completed it.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from images.models import BoundingBox, Image
from images.processors.annotation import (
    PERSON_CATEGORY,
    auto_approve_single_human,
    get_service_annotator,
)


class Command(BaseCommand):
    """Mark single high-confidence human images as complete for the species pipeline."""

    help = (
        "Auto-approve backlog images that contain exactly one high-confidence human bounding box. "
        "The expert service account votes to accept the box and category, completing the category "
        "and species pipelines. Idempotent and resumable: images already voted on by the service "
        "account are skipped."
    )

    def add_arguments(self, parser) -> None:
        """Register command-line flags for scoped, tunable rollout."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many images qualify without modifying anything.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Approve at most this many images (for testing a small selection before ramping up).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Number of images to process per transaction (default 2000).",
        )
        parser.add_argument(
            "--confidence",
            type=float,
            default=None,
            help="Confidence cutoff for the person box. Defaults to settings.SINGLE_HUMAN_AUTO_APPROVE_CONFIDENCE.",
        )

    def handle(self, *args, **options) -> None:
        """Query qualifying images and auto-approve them in batches."""
        dry_run = options["dry_run"]
        limit = options["limit"]
        batch_size = options["batch_size"]
        confidence = options["confidence"]
        if confidence is None:
            confidence = settings.SINGLE_HUMAN_AUTO_APPROVE_CONFIDENCE

        ############### find qualifying images ###############
        service_annotator = get_service_annotator()
        qualifying_ids = self._get_qualifying_image_ids(confidence, service_annotator)
        if limit is not None:
            qualifying_ids = qualifying_ids[:limit]

        total = len(qualifying_ids)
        logging.info(f"Found {total} images with a single person bbox at confidence >= {confidence}.")

        if dry_run:
            logging.info("Dry run: no images modified.")
            self.stdout.write(f"[dry-run] {total} images would be auto-approved.")
            return

        ############### approve in batches ###############
        approved = 0
        skipped = 0
        for start in range(0, total, batch_size):
            batch = qualifying_ids[start : start + batch_size]
            # One transaction per batch: an interruption leaves no image half-approved.
            with transaction.atomic():
                for image in Image.objects.filter(id__in=batch):
                    if auto_approve_single_human(image):
                        approved += 1
                    else:
                        # The box set changed between query and processing (e.g. re-inference).
                        skipped += 1
            logging.info(f"Processed {min(start + batch_size, total)}/{total} (approved {approved}, skipped {skipped}).")

        self.stdout.write(f"Auto-approved {approved} images ({skipped} skipped).")

    def _get_qualifying_image_ids(self, confidence: float, service_annotator) -> list[str]:
        """Return ids of images with exactly one high-confidence, not-yet-approved person box.

        Queried in two steps to avoid the JOIN-inflated ``Count`` pitfall: the exact-one-box
        count is computed on its own query, then the person/confidence/already-approved filter
        runs over that id set on the ``BoundingBox`` table.

        Args:
            confidence: Minimum bounding-box confidence for eligibility.
            service_annotator: The expert service-account annotator whose prior accept vote marks
                an image as already auto-approved (used to skip completed images on re-runs).

        Returns:
            A list of qualifying image ids.
        """
        # Step 1: images with exactly one bounding box.
        single_bbox_ids = (
            Image.objects.filter(processed=True, upload__deleted=False)
            .annotate(bbox_count=Count("boundingbox"))
            .filter(bbox_count=1)
            .values_list("id", flat=True)
        )

        # Step 2: of those, the single box is a high-confidence person not already approved by the
        # service account (the durable marker that keeps the command idempotent and resumable).
        qualifying_ids = (
            BoundingBox.objects.filter(
                image_id__in=single_bbox_ids,
                confidence__gte=confidence,
                category__name=PERSON_CATEGORY,
            )
            .exclude(category__accepted_by=service_annotator)
            .values_list("image_id", flat=True)
        )

        return list(qualifying_ids)
