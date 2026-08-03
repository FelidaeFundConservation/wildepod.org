"""
Backfill the `validity` field on Category, Species, Activity, and BoundingBox.

Designed for one-time production use after the schema migration that adds
`validity` to Category/Species/Activity and extends BoundingBox.validity
choices. Idempotent — safe to re-run.

Mechanics:
- Cursor pagination by UUID (id__gt=last_id ORDER BY id) for stable iteration
  without OFFSET drift.
- Per-batch atomic transactions, so the command is safe to interrupt and
  resume via --resume-from.
- bulk_update() bypasses save(), so backfilled rows don't bump `modified`.
- Annotation models (Category, Species, Activity) are processed first via
  compute_validity().
- BoundingBox.validity is then cascaded from its children:
    any child VALID            -> VALID
    any UNCERTAIN or NULL      -> UNCERTAIN
    all INVALID                -> INVALID
    no children at all         -> NULL (UNSEEN)

Usage:
    python manage.py backfill_validity                      # all four models
    python manage.py backfill_validity --model=Category
    python manage.py backfill_validity --model=BoundingBox  # cascade only
    python manage.py backfill_validity --resume-from=<uuid>
"""

import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch
from images.models import Activity, Annotator, BoundingBox, Category, Species
from images.models.annotation import Validity
from siteapps.images.processors.annotation import compute_validity

ANNOTATION_MODELS = {
    "Category": Category,
    "Species": Species,
    "Activity": Activity,
}
ALL_MODELS = {**ANNOTATION_MODELS, "BoundingBox": BoundingBox}

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class Command(BaseCommand):
    help = "Backfill the validity field on Category, Species, Activity, and BoundingBox. Resumable, batched."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=list(ALL_MODELS.keys()),
            help="Limit backfill to a single model. Default: all four (annotation models first, then BoundingBox cascade).",
        )
        parser.add_argument(
            "--resume-from",
            type=str,
            help="UUID to resume from (exclusive). Only used when --model is specified.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Rows per batch. Default 1000.",
        )

    def handle(self, *args, model=None, resume_from=None, batch_size=1000, **opts):
        if model:
            self._backfill_one(model, resume_from, batch_size)
            return

        # Full run: annotation models first, then BoundingBox cascade.
        if resume_from:
            self.stderr.write("--resume-from is only honored with --model. Ignoring for full run.")
        for model_name in ANNOTATION_MODELS:
            self._backfill_one(model_name, None, batch_size)
        self._backfill_one("BoundingBox", None, batch_size)

    def _backfill_one(self, model_name: str, resume_from, batch_size: int):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== Backfilling {model_name} ==="))
        if model_name == "BoundingBox":
            self._backfill_bboxes(resume_from, batch_size)
        else:
            self._backfill_annotation_model(ANNOTATION_MODELS[model_name], resume_from, batch_size)

    def _backfill_annotation_model(self, Model, resume_from, batch_size: int):
        last_id = resume_from or ZERO_UUID
        processed = 0
        start_time = time.monotonic()
        annotator_qs = Annotator.objects.select_related("human")
        while True:
            with transaction.atomic():
                batch = list(
                    Model.objects.filter(id__gt=last_id)
                    .order_by("id")
                    .select_related("created_by__human", "created_by__bot")
                    .prefetch_related(
                        Prefetch("accepted_by", queryset=annotator_qs),
                        Prefetch("rejected_by", queryset=annotator_qs),
                    )[:batch_size]
                )
                if not batch:
                    break
                for obj in batch:
                    obj.validity = compute_validity(obj).validity
                Model.objects.bulk_update(batch, ["validity"])
                last_id = str(batch[-1].id)
                processed += len(batch)
            elapsed = time.monotonic() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            self.stdout.write(
                f"  {Model.__name__}: {processed:,} processed "
                f"({rate:.0f} rows/sec, elapsed {elapsed:.0f}s, last id {last_id})"
            )
            self.stdout.flush()
        self.stdout.write(self.style.SUCCESS(f"  Done: {processed:,} {Model.__name__} rows updated"))

    def _backfill_bboxes(self, resume_from, batch_size: int):
        """
        Cascade rule from children:
          any child VALID     -> VALID
          any UNCERTAIN/NULL  -> UNCERTAIN
          all INVALID         -> INVALID
          no children at all  -> NULL (UNSEEN)
        """
        last_id = resume_from or ZERO_UUID
        processed = 0
        while True:
            with transaction.atomic():
                batch = list(
                    BoundingBox.objects.filter(id__gt=last_id)
                    .order_by("id")
                    .prefetch_related("category_set", "species_set", "activity_set")[:batch_size]
                )
                if not batch:
                    break
                for bbox in batch:
                    bbox.validity = self._cascade_validity(bbox)
                BoundingBox.objects.bulk_update(batch, ["validity"])
                last_id = str(batch[-1].id)
                processed += len(batch)
            self.stdout.write(f"  BoundingBox: {processed:,} processed (last id {last_id})")
        self.stdout.write(self.style.SUCCESS(f"  Done: {processed:,} BoundingBox rows updated"))

    @staticmethod
    def _cascade_validity(bbox: BoundingBox):
        child_validities = set()
        for collection in (bbox.category_set.all(), bbox.species_set.all(), bbox.activity_set.all()):
            for child in collection:
                child_validities.add(child.validity)

        if not child_validities:
            return None  # UNSEEN
        if Validity.VALID in child_validities:
            return Validity.VALID
        if Validity.UNCERTAIN in child_validities or None in child_validities:
            return Validity.UNCERTAIN
        return Validity.INVALID
