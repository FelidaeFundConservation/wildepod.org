# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Backlog auto-approval of single high-confidence human images.

Retroactively completes already-uploaded images that contain exactly one bounding box
classified as a high-confidence person, so they leave the species (and human-behavior)
annotation queues without ever being served to a human annotator. Each approval reuses the
same automation-bot voting routine as the forward (upload-time) path, so an auto-annotated
image carries the identical audit trail regardless of which path completed it.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils.dateparse import parse_date
from images.models import Annotator, BoundingBox, Image
from images.processors.annotation import (
    AUTOMATION_BOT_NAME,
    AUTOMATION_BOT_VERSION,
    PERSON_CATEGORY,
    auto_approve_single_human,
    get_automation_annotator,
)


class Command(BaseCommand):
    """Mark single high-confidence human images as complete for the species pipeline."""

    help = (
        "Auto-approve backlog images that contain exactly one high-confidence human bounding box. "
        "The automation bot annotator votes to accept the box and category, completing the category "
        "and species pipelines. Idempotent and resumable: images already voted on by the automation "
        "annotator are skipped."
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
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Include images captured on or after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Include images captured on or before this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--camera-station",
            type=str,
            default=None,
            help="Limit images to an exact camera station ID.",
        )
        parser.add_argument(
            "--macro-site",
            type=str,
            default=None,
            help="Limit images to an exact macro-site name.",
        )

    def handle(self, *args, **options) -> None:
        """Query qualifying images and auto-approve them in batches."""
        dry_run = options["dry_run"]
        limit = options["limit"]
        batch_size = options["batch_size"]
        confidence = options["confidence"]
        if confidence is None:
            confidence = settings.SINGLE_HUMAN_AUTO_APPROVE_CONFIDENCE

        start_date = self._parse_date_option("--start-date", options["start_date"])
        end_date = self._parse_date_option("--end-date", options["end_date"])
        if start_date and end_date and start_date > end_date:
            raise CommandError("--start-date must be on or before --end-date.")

        scope = {
            "start_date": start_date,
            "end_date": end_date,
            "camera_station": options["camera_station"],
            "macro_site": options["macro_site"],
        }

        ############### find qualifying images ###############
        if dry_run:
            automation_annotator = Annotator.objects.filter(
                type="bot",
                bot__name=AUTOMATION_BOT_NAME,
                bot__version=AUTOMATION_BOT_VERSION,
            ).first()
        else:
            automation_annotator = get_automation_annotator()
        qualifying_ids = self._get_qualifying_image_ids(confidence, automation_annotator, **scope)
        if limit is not None:
            qualifying_ids = qualifying_ids[:limit]

        total = len(qualifying_ids)
        scope_description = self._format_scope(**scope)
        logging.info(
            f"Found {total} images with a single person bbox at confidence >= {confidence}; "
            f"scope: {scope_description}."
        )

        if dry_run:
            logging.info("Dry run: no images modified.")
            self.stdout.write(f"[dry-run] {total} images would be auto-approved (scope: {scope_description}).")
            return

        ############### approve in batches ###############
        approved = 0
        skipped = 0
        for start in range(0, total, batch_size):
            batch = qualifying_ids[start : start + batch_size]
            # One transaction per batch: an interruption leaves no image half-approved.
            with transaction.atomic():
                for image in Image.objects.filter(id__in=batch):
                    if auto_approve_single_human(image, confidence_cutoff=confidence):
                        approved += 1
                    else:
                        # The box set changed between query and processing (e.g. re-inference).
                        skipped += 1
            logging.info(
                f"Processed {min(start + batch_size, total)}/{total} (approved {approved}, skipped {skipped})."
            )

        self.stdout.write(f"Auto-approved {approved} images ({skipped} skipped; scope: {scope_description}).")

    def _get_qualifying_image_ids(
        self,
        confidence: float,
        automation_annotator,
        start_date=None,
        end_date=None,
        camera_station: str | None = None,
        macro_site: str | None = None,
    ) -> list[str]:
        """Return ids of scoped, high-confidence, not-yet-approved single-person images.

        Queried in two steps to avoid the JOIN-inflated ``Count`` pitfall: the exact-one-box
        count is computed on its own query, then the person/confidence/already-approved filter
        runs over that id set on the ``BoundingBox`` table.

        Args:
            confidence: Minimum bounding-box confidence for eligibility.
            automation_annotator: The automation bot annotator whose prior accept vote marks
                an image as already auto-approved (used to skip completed images on re-runs).
            start_date: Earliest capture date to include, or None for no lower bound.
            end_date: Latest capture date to include, or None for no upper bound.
            camera_station: Exact camera station ID to include, or None for every station.
            macro_site: Exact macro-site name to include, or None for every macro-site.

        Returns:
            A list of qualifying image ids.
        """
        # Step 1: scoped images with exactly one bounding box.
        images = Image.objects.filter(processed=True, upload__deleted=False)
        if start_date:
            images = images.filter(trigger_timestamp__date__gte=start_date)
        if end_date:
            images = images.filter(trigger_timestamp__date__lte=end_date)
        if camera_station:
            images = images.filter(upload__camera_station__station_id=camera_station)
        if macro_site:
            images = images.filter(upload__camera_station__micro_site__macro_site__name=macro_site)

        single_bbox_ids = (
            images.annotate(bbox_count=Count("boundingbox")).filter(bbox_count=1).values_list("id", flat=True)
        )

        # Step 2: of those, the single box is a high-confidence person not already approved by the
        # automation annotator (the durable marker that keeps the command idempotent and resumable).
        qualifying_boxes = BoundingBox.objects.filter(
            image_id__in=single_bbox_ids,
            confidence__gte=confidence,
            category__name=PERSON_CATEGORY,
        )
        if automation_annotator is not None:
            qualifying_boxes = qualifying_boxes.exclude(category__accepted_by=automation_annotator)

        return list(qualifying_boxes.values_list("image_id", flat=True))

    @staticmethod
    def _parse_date_option(option_name: str, raw_value: str | None):
        """Parse one optional ISO date argument or raise a command-friendly error."""
        if raw_value is None:
            return None
        parsed = parse_date(raw_value)
        if parsed is None:
            raise CommandError(f"{option_name} must use YYYY-MM-DD format; received '{raw_value}'.")
        return parsed

    @staticmethod
    def _format_scope(
        start_date=None,
        end_date=None,
        camera_station: str | None = None,
        macro_site: str | None = None,
    ) -> str:
        """Return a readable description of the active backlog filters."""
        filters = []
        if start_date:
            filters.append(f"start_date={start_date.isoformat()}")
        if end_date:
            filters.append(f"end_date={end_date.isoformat()}")
        if camera_station:
            filters.append(f"camera_station={camera_station}")
        if macro_site:
            filters.append(f"macro_site={macro_site}")
        return ", ".join(filters) if filters else "all eligible images"
