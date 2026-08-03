"""
Dry-run report: show what compute_validity() would produce for every Category,
Species, and Activity in the DB. No writes.

Run this before backfill_validity to sanity-check the distribution of new
validity values. Unexpected skew (e.g. nearly everything INVALID) would
indicate a problem with the new rules or with the underlying vote data.

Note: BaseAnnotationManager.valid() / uncertain() / valid_or_uncertain() raise
FieldError on Category/Species/Activity because the inherited `keep` filter
references confidence_threshold, which only exists on BoundingBox. So there
is no "current rules" baseline to compare against on these models. The
distribution this command prints is purely the new validity assignment.

Usage:
    python manage.py report_validity_flips
    python manage.py report_validity_flips --model=Category
    python manage.py report_validity_flips --batch-size=2000
"""

import time
from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from images.models import Activity, Annotator, Category, Species
from siteapps.images.processors.annotation import compute_validity

MODEL_MAP = {
    "Category": Category,
    "Species": Species,
    "Activity": Activity,
}


class Command(BaseCommand):
    help = "Report the distribution of validity values compute_validity() would assign. Read-only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=list(MODEL_MAP.keys()),
            help="Limit report to a single model. Default: all three.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Rows to fetch per chunk_size. Default 1000.",
        )

    def handle(self, *args, model=None, batch_size=1000, **opts):
        models_to_process = [MODEL_MAP[model]] if model else [Category, Species, Activity]
        for Model in models_to_process:
            self._report_model(Model, batch_size)

    def _report_model(self, Model, batch_size: int):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {Model.__name__} ==="))

        # Prefetch via Prefetch(queryset=...) so the annotator's `human` FK is
        # joined at prefetch time. compute_validity() then reads from cache
        # without extra queries.
        annotator_qs = Annotator.objects.select_related("human")
        qs = (
            Model.objects.all()
            .select_related("created_by__human", "created_by__bot")
            .prefetch_related(
                Prefetch("accepted_by", queryset=annotator_qs),
                Prefetch("rejected_by", queryset=annotator_qs),
            )
            .order_by("id")
        )

        total = 0
        by_validity: Counter = Counter()
        by_has_votes: Counter = Counter()
        score_distribution: Counter = Counter()
        start_time = time.monotonic()
        last_log_time = start_time
        # Heartbeat every 5k rows; report rate + ETA so progress is visible.
        log_interval = max(1000, min(5000, batch_size * 5))

        for obj in qs.iterator(chunk_size=batch_size):
            total += 1
            result = compute_validity(obj)
            by_validity[result.validity] += 1
            score_distribution[self._score_bucket(result.score)] += 1
            # Use prefetched counts from VoteResult instead of re-querying.
            if result.accepted_count > 0 or result.rejected_count > 0:
                by_has_votes["with_votes"] += 1
            else:
                by_has_votes["creator_only"] += 1

            if total % log_interval == 0:
                now = time.monotonic()
                elapsed = now - start_time
                interval = now - last_log_time
                interval_rate = log_interval / interval if interval > 0 else 0
                overall_rate = total / elapsed if elapsed > 0 else 0
                self.stdout.write(
                    f"  {Model.__name__}: {total:,} rows "
                    f"({overall_rate:.0f} rows/sec overall, {interval_rate:.0f} last batch, "
                    f"elapsed {elapsed:.0f}s)"
                )
                self.stdout.flush()
                last_log_time = now

        elapsed = time.monotonic() - start_time
        self.stdout.write(f"\nTotal {Model.__name__}: {total:,} in {elapsed:.1f}s")
        if not total:
            self.stdout.write("  (no rows)")
            return
        self._print_distribution("Validity", by_validity, total)
        self._print_distribution("Has any votes", by_has_votes, total)
        self._print_distribution("Score bucket", score_distribution, total)

    @staticmethod
    def _score_bucket(score: int) -> str:
        if score <= -5:
            return "<=-5  (definitively INVALID, staff reject or many normal rejects)"
        if score < 0:
            return "-4..-1 (negative, UNCERTAIN or INVALID at -2)"
        if score == 0:
            return "0     (perfectly split UNCERTAIN)"
        if score == 1:
            return "1     (UNCERTAIN, bot creator alone)"
        if score < 5:
            return "2..4  (VALID via 2+ normal votes)"
        return ">=5   (VALID via staff or many normal votes)"

    def _print_distribution(self, label: str, counts: Counter, total: int):
        self.stdout.write(f"\n  {label}:")
        for key, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            pct = 100.0 * count / total
            self.stdout.write(f"    {str(key):60} {count:>10,}  ({pct:5.1f}%)")
