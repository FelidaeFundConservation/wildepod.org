"""
Times the real MegaDetector / Species Detector Cloud Run calls against existing
images, so a latency change (e.g. moving detection off the sync request path)
can be measured before/after instead of guessed at.

This calls the real endpoints in images.processors.image.run_model_inference,
which means it makes real network calls and, for MegaDetector, writes real
BoundingBox/Category rows (existing rows are reused via get_or_create). Point
this at staging with disposable/test images, not prod.

Requires the same local setup as any other cloud-connected run (see README
"Local with Cloud" section): GOOGLE_CLOUD_PROJECT set, and in DEBUG mode an
ID_TOKEN env var from `gcloud auth print-identity-token -q`.

Usage:
    # Time 10 random already-thumbnailed images, label the run "baseline-sync"
    python manage.py benchmark_species_pipeline --limit 10 --label baseline-sync --settings=config.settings.staging

    # Re-run against the same images after a code change, to compare directly
    python manage.py benchmark_species_pipeline --image-ids <uuid1> <uuid2> --label after-fix --settings=config.settings.staging

Writes one JSON file per run to benchmarks/<label>-<timestamp>.json. Open
scratch/benchmark_dashboard.html in a browser and load the file(s) to compare.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from images.models import Image
from images.processors.image import run_model_inference

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path(__file__).resolve().parents[4] / "benchmarks"

# This command writes to whatever database it is pointed at, so it refuses to run
# against a live deployment. Both config.settings.prod and config.settings.bhutan
# are production; matching on the module's last segment also catches variants like
# "prod_local" or a copied "my_prod" settings module.
PRODUCTION_SETTINGS_MARKERS = ("prod", "bhutan")


class Command(BaseCommand):
    help = "Time real MegaDetector / Species Detector calls against existing images and log results for scratch/benchmark_dashboard.html"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Number of random images to benchmark")
        parser.add_argument(
            "--label", type=str, default="run", help="Label for this run, e.g. 'baseline-sync' or 'after-fix'"
        )
        parser.add_argument("--image-ids", nargs="*", help="Specific image UUIDs to benchmark instead of --limit")
        parser.add_argument(
            "--output", type=str, default=None, help="Output JSON path (default: benchmarks/<label>-<timestamp>.json)"
        )
        parser.add_argument("--skip-species", action="store_true", help="Only time the MegaDetector call")

    def _reject_production(self):
        settings_module = getattr(settings, "SETTINGS_MODULE", None) or os.environ.get("DJANGO_SETTINGS_MODULE", "")
        leaf = settings_module.rsplit(".", 1)[-1].lower()
        if any(marker in leaf for marker in PRODUCTION_SETTINGS_MARKERS):
            raise CommandError(
                f"Refusing to run against production settings ({settings_module or 'unknown'}). "
                "This command makes real model calls and writes BoundingBox/Category rows. "
                "Re-run with --settings=config.settings.staging against disposable images."
            )

    def handle(self, *args, **options):
        self._reject_production()
        limit = options["limit"]
        label = options["label"]
        skip_species = options["skip_species"]

        qs = Image.objects.exclude(thumbnail_gcloud_path="").exclude(thumbnail_gcloud_path__isnull=True)
        if options["image_ids"]:
            qs = qs.filter(id__in=options["image_ids"])
        else:
            qs = qs.order_by("?")[:limit]

        images = list(qs)
        if not images:
            self.stderr.write(self.style.ERROR("No images found with a thumbnail to benchmark against."))
            return

        output_path = (
            Path(options["output"]) if options["output"] else DEFAULT_LOG_DIR / f"{label}-{int(time.time())}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        results = []
        for i, image in enumerate(images, 1):
            self.stdout.write(f"[{i}/{len(images)}] Benchmarking image {image.id}...")
            record = {"image_id": str(image.id), "stages": {}, "success": True, "error": None}
            total_start = time.perf_counter()
            try:
                t0 = time.perf_counter()
                run_model_inference(image, species=False)
                record["stages"]["megadetector_ms"] = round((time.perf_counter() - t0) * 1000, 1)

                if not skip_species:
                    t0 = time.perf_counter()
                    run_model_inference(image, species=True)
                    record["stages"]["species_detector_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            except Exception as e:
                record["success"] = False
                record["error"] = str(e)
                logger.exception(f"Benchmark failed on image {image.id}")

            record["total_ms"] = round((time.perf_counter() - total_start) * 1000, 1)
            results.append(record)
            status = "ok" if record["success"] else f"FAILED: {record['error']}"
            self.stdout.write(f"  -> {record['total_ms']}ms ({status})")

        payload = {
            "run_id": str(uuid.uuid4()),
            "label": label,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "images": results,
        }
        output_path.write_text(json.dumps(payload, indent=2))
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(results)} results to {output_path}"))
        self.stdout.write("Open scratch/benchmark_dashboard.html in a browser and load this file to visualize.")
