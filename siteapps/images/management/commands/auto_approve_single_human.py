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

import datetime
import logging
import time
from itertools import islice

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_date
from images.models import Annotator, BoundingBox, Category, Image
from images.models.annotation import Validity
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
        parser.add_argument(
            "--timing",
            action="store_true",
            help="Print section-level timing diagnostics for performance analysis.",
        )

    def handle(self, *args, **options) -> None:
        """Query qualifying images and auto-approve them in batches."""
        dry_run = options["dry_run"]
        timing = options["timing"]
        command_started = time.perf_counter()
        limit = options["limit"]
        batch_size = options["batch_size"]
        if batch_size <= 0:
            raise CommandError("--batch-size must be greater than zero.")
        if limit is not None and limit < 0:
            raise CommandError("--limit must be zero or greater.")
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
        candidate_started = time.perf_counter()
        qualifying_ids = self._get_qualifying_image_ids(confidence, automation_annotator, **scope)
        if limit is None:
            total = qualifying_ids.count()
            count_mode = "full"
        else:
            # Counting the unrestricted backlog defeats the purpose of --limit. Remove the
            # paging order so PostgreSQL can stop after finding `limit` distinct candidates.
            total = qualifying_ids.order_by()[:limit].count()
            count_mode = "limited"
        self._write_timing(timing, "candidate_count", candidate_started, candidates=total, mode=count_mode)
        scope_description = self._format_scope(**scope)
        logging.info(
            f"Found {total} images with a single person bbox at confidence >= {confidence}; "
            f"scope: {scope_description}."
        )

        if dry_run:
            logging.info("Dry run: no images modified.")
            self.stdout.write(f"[dry-run] {total} images would be auto-approved (scope: {scope_description}).")
            self._write_timing(timing, "command_total", command_started, processed=0)
            return

        ############### approve in batches ###############
        approved = 0
        skipped = 0
        processed = 0
        candidate_source = qualifying_ids if limit is None else qualifying_ids[:limit]
        candidate_iterator = candidate_source.values_list("image_id", flat=True).iterator(chunk_size=batch_size)
        while processed < total:
            page_started = time.perf_counter()
            page_size = min(batch_size, total - processed)
            batch = list(islice(candidate_iterator, page_size))
            self._write_timing(timing, "candidate_page", page_started, page_size=len(batch))
            if not batch:
                break

            # One transaction per batch: an interruption leaves no image half-approved.
            batch_started = time.perf_counter()
            with transaction.atomic():
                batch_approved, batch_skipped = self._approve_batch(
                    batch,
                    confidence=confidence,
                    automation_annotator=automation_annotator,
                    batch_size=batch_size,
                    timing=timing,
                )
                approved += batch_approved
                skipped += batch_skipped
            self._write_timing(
                timing,
                "batch_transaction",
                batch_started,
                batch_size=len(batch),
                approved=batch_approved,
                skipped=batch_skipped,
            )
            processed += len(batch)
            logging.info(f"Processed {processed}/{total} (approved {approved}, skipped {skipped}).")

        self.stdout.write(f"Auto-approved {approved} images ({skipped} skipped; scope: {scope_description}).")
        self._write_timing(timing, "command_total", command_started, processed=processed)

    def _get_qualifying_image_ids(
        self,
        confidence: float,
        automation_annotator,
        start_date=None,
        end_date=None,
        camera_station: str | None = None,
        macro_site: str | None = None,
    ):
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
            An ordered queryset of qualifying bounding boxes. Each image id occurs once.
        """
        # Step 1: scoped images with exactly one bounding box.
        images = Image.objects.filter(processed=True, upload__deleted=False)
        if start_date:
            start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
            images = images.filter(trigger_timestamp__gte=start_datetime)
        if end_date:
            end_datetime = timezone.make_aware(
                datetime.datetime.combine(end_date + datetime.timedelta(days=1), datetime.time.min)
            )
            images = images.filter(trigger_timestamp__lt=end_datetime)
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

        # A malformed/legacy box can contain duplicate person categories. Distinct image ids keep
        # paging stable; unusual category shapes are handled by the per-image fallback below.
        return qualifying_boxes.order_by().values("image_id").distinct().order_by("image_id")

    def _approve_batch(
        self,
        image_ids,
        *,
        confidence: float,
        automation_annotator: Annotator,
        batch_size: int,
        timing: bool = False,
    ) -> tuple[int, int]:
        """Bulk-approve the strict common case and fall back for unusual rows.

        The fast path requires one bounding box and exactly one category, which must be person.
        Candidate discovery already applies the durable eligibility filters, while this method
        revalidates the mutable box/category shape inside the write transaction.
        """
        load_started = time.perf_counter()
        category_queryset = Category.objects.order_by("id")
        bbox_queryset = BoundingBox.objects.order_by("id").prefetch_related(
            Prefetch("category_set", queryset=category_queryset, to_attr="_auto_approve_categories")
        )
        images = list(
            Image.objects.select_for_update()
            .select_related("upload")
            .filter(id__in=image_ids)
            .prefetch_related(Prefetch("boundingbox_set", queryset=bbox_queryset, to_attr="_auto_approve_bboxes"))
        )
        self._write_timing(timing, "batch_load", load_started, images=len(images))

        classify_started = time.perf_counter()
        fast_path = []
        fallback = []
        for image in images:
            boxes = image._auto_approve_bboxes
            if len(boxes) != 1:
                fallback.append(image)
                continue
            bbox = boxes[0]
            categories = bbox._auto_approve_categories
            if bbox.confidence < confidence or len(categories) != 1 or categories[0].name != PERSON_CATEGORY:
                fallback.append(image)
                continue
            fast_path.append((image, bbox, categories[0]))
        self._write_timing(
            timing,
            "batch_classify",
            classify_started,
            fast_path=len(fast_path),
            fallback=len(fallback),
        )

        if fast_path:
            now = timezone.now()
            fast_image_ids = [image.id for image, _, _ in fast_path]
            bbox_ids = [bbox.id for _, bbox, _ in fast_path]
            category_ids = [category.id for _, _, category in fast_path]

            votes_started = time.perf_counter()
            bbox_accept_model = BoundingBox.accepted_by.through
            category_accept_model = Category.accepted_by.through
            bbox_accept_model.objects.bulk_create(
                [
                    bbox_accept_model(boundingbox_id=bbox_id, annotator_id=automation_annotator.id)
                    for bbox_id in bbox_ids
                ],
                ignore_conflicts=True,
                batch_size=batch_size,
            )
            category_accept_model.objects.bulk_create(
                [
                    category_accept_model(category_id=category_id, annotator_id=automation_annotator.id)
                    for category_id in category_ids
                ],
                ignore_conflicts=True,
                batch_size=batch_size,
            )

            BoundingBox.rejected_by.through.objects.filter(
                boundingbox_id__in=bbox_ids,
                annotator_id=automation_annotator.id,
            ).delete()
            Category.rejected_by.through.objects.filter(
                category_id__in=category_ids,
                annotator_id=automation_annotator.id,
            ).delete()
            self._write_timing(timing, "batch_votes", votes_started, rows=len(fast_path))

            updates_started = time.perf_counter()
            Category.objects.filter(id__in=category_ids).update(validity=Validity.VALID, modified=now)
            BoundingBox.objects.filter(id__in=bbox_ids).update(validity=Validity.VALID, modified=now)
            Image.objects.filter(id__in=fast_image_ids).update(
                category_pipeline_complete=True,
                species_pipeline_complete=True,
                has_humans=True,
                has_animals=False,
                has_vehicles=False,
                has_uncertain_bbox=False,
                modified=now,
            )
            self._write_timing(timing, "batch_state_updates", updates_started, rows=len(fast_path))

        fallback_started = time.perf_counter()
        approved = len(fast_path)
        skipped = 0
        for image in fallback:
            if auto_approve_single_human(
                image,
                confidence_cutoff=confidence,
                automation_annotator=automation_annotator,
            ):
                approved += 1
            else:
                skipped += 1
        self._write_timing(timing, "batch_fallback", fallback_started, rows=len(fallback))

        # Candidate ids can disappear between discovery and the locked batch fetch.
        skipped += len(image_ids) - len(images)
        return approved, skipped

    def _write_timing(self, enabled: bool, section: str, started: float, **details) -> None:
        """Print one machine-readable timing line when diagnostics are enabled."""
        if not enabled:
            return
        elapsed = time.perf_counter() - started
        detail_text = " ".join(f"{key}={value}" for key, value in details.items())
        self.stdout.write(f"[timing] section={section} seconds={elapsed:.6f} {detail_text}".rstrip())

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
