# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Fix Bhutan image timestamps by reading EXIF DateTimeOriginal from the original
Dropbox files and using it as the ground truth for Bhutan local time.

The cameras record correct local time in EXIF DateTimeOriginal, but the EXIF
timezone offset is misconfigured (varies per camera: -10:00, -09:00, +11:00, etc.).
This caused Dropbox and Django to store incorrect UTC timestamps.

This command bypasses all conversion logic and reads the EXIF directly.
"""

import concurrent.futures
import logging
import threading
import time
from datetime import datetime
from io import BytesIO

import pytz
import requests
from django.core.management.base import BaseCommand
from django.db.models import Count
from images.models import Image
from images.utils.dropbox_client import create_dropbox_client
from PIL import Image as PILImage

logger = logging.getLogger(__name__)

BHUTAN_TZ = pytz.timezone("Asia/Thimphu")

# EXIF IFD tag IDs
EXIF_IFD_TAG = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003

# Only download the first 64KB to get EXIF header (much faster than full image)
EXIF_HEADER_BYTES = 65536

# Dropbox rate limit friendly thread count
MAX_DOWNLOAD_THREADS = 10


def read_exif_datetime_from_bytes(image_bytes):
    """Extract DateTimeOriginal from image bytes. Returns naive datetime or None."""
    try:
        pil_image = PILImage.open(BytesIO(image_bytes))
        exif_data = pil_image.getexif()
        exif_ifd = exif_data.get_ifd(EXIF_IFD_TAG)
        dt_str = exif_ifd.get(TAG_DATETIME_ORIGINAL)
        if dt_str:
            return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def download_exif_via_temp_link(dbx, dropbox_path):
    """Download only the EXIF header using a temporary link + Range request.

    Falls back to full download if Range request fails.
    Returns (exif_datetime_naive, error_string_or_none).
    """
    try:
        link_result = dbx.files_get_temporary_link(dropbox_path)
        url = link_result.link

        # Try partial download first (EXIF is in the JPEG header)
        response = requests.get(url, headers={"Range": f"bytes=0-{EXIF_HEADER_BYTES - 1}"}, timeout=30)
        if response.status_code in (200, 206):
            exif_dt = read_exif_datetime_from_bytes(response.content)
            if exif_dt:
                return exif_dt, None

            # Partial download didn't have EXIF or couldn't parse — try full download
            if response.status_code == 206:
                full_response = requests.get(url, timeout=60)
                if full_response.status_code == 200:
                    exif_dt = read_exif_datetime_from_bytes(full_response.content)
                    if exif_dt:
                        return exif_dt, None
                    return None, "no EXIF DateTimeOriginal in file"

        return None, f"HTTP {response.status_code}"
    except Exception as e:
        return None, str(e)


def download_exif_direct(dbx, dropbox_path):
    """Download via Dropbox SDK and extract EXIF. Fallback method.

    Returns (exif_datetime_naive, error_string_or_none).
    """
    try:
        _, response = dbx.files_download(dropbox_path)
        exif_dt = read_exif_datetime_from_bytes(response.content)
        if exif_dt:
            return exif_dt, None
        return None, "no EXIF DateTimeOriginal in file"
    except Exception as e:
        return None, str(e)


class Command(BaseCommand):
    help = "Fix Bhutan timestamps using EXIF DateTimeOriginal as ground truth."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without saving.",
        )
        parser.add_argument(
            "--camera-station",
            type=str,
            default=None,
            help="Limit to a specific camera station (substring match).",
        )
        parser.add_argument(
            "--upload-id",
            type=str,
            default=None,
            help="Limit to a specific upload ID.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of images to process and save per batch (default: 500).",
        )
        parser.add_argument(
            "--threads",
            type=int,
            default=MAX_DOWNLOAD_THREADS,
            help=f"Number of parallel Dropbox download threads (default: {MAX_DOWNLOAD_THREADS}).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit total number of images to process (for testing).",
        )
        parser.add_argument(
            "--use-sdk-download",
            action="store_true",
            help="Use Dropbox SDK download instead of temp link + Range request.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        camera_station = options["camera_station"]
        upload_id = options["upload_id"]
        batch_size = options["batch_size"]
        max_threads = options["threads"]
        limit = options["limit"]
        use_sdk = options["use_sdk_download"]

        dbx = create_dropbox_client()
        if dbx is None:
            self.stderr.write(self.style.ERROR("Could not create Dropbox client."))
            return

        # Query images
        qs = Image.objects.filter(trigger_timestamp__isnull=False).order_by("trigger_timestamp")
        if camera_station:
            qs = qs.filter(upload__camera_station__station_id__icontains=camera_station)
        if upload_id:
            qs = qs.filter(upload_id=upload_id)

        total = qs.count()
        if limit:
            total = min(total, limit)

        self.stdout.write(f"Found {total} images to process.")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved."))
        self.stdout.write(f"Using {max_threads} download threads, batch size {batch_size}.")
        self.stdout.write(f"Download method: {'SDK direct' if use_sdk else 'temp link + Range'}\n")

        # Stats
        stats_lock = threading.Lock()
        stats = {
            "processed": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped_no_exif": 0,
            "skipped_error": 0,
            "skipped_no_path": 0,
        }
        start_time = time.time()

        def process_image(image):
            """Download EXIF and compute correct timestamp for a single image."""
            if not image.dropbox_file_path:
                return image, None, "no dropbox path"

            # Download and read EXIF
            if use_sdk:
                exif_dt, error = download_exif_direct(dbx, image.dropbox_file_path)
            else:
                exif_dt, error = download_exif_via_temp_link(dbx, image.dropbox_file_path)
                if error and "not_found" not in error:
                    # Retry with SDK download as fallback
                    exif_dt, error = download_exif_direct(dbx, image.dropbox_file_path)

            if error:
                return image, None, error
            if exif_dt is None:
                return image, None, "no EXIF"

            # EXIF DateTimeOriginal IS the correct Bhutan local time
            correct_timestamp = BHUTAN_TZ.localize(exif_dt)
            return image, correct_timestamp, None

        # Process in batches
        processed_total = 0
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_images = list(qs[batch_start:batch_end])

            if not batch_images:
                break

            # Download EXIF in parallel
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                future_to_img = {executor.submit(process_image, img): img for img in batch_images}
                for future in concurrent.futures.as_completed(future_to_img):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        img = future_to_img[future]
                        results.append((img, None, str(e)))

            # Apply updates
            images_to_update = []
            for image, correct_timestamp, error in results:
                with stats_lock:
                    stats["processed"] += 1

                if error:
                    if "not_found" in error:
                        with stats_lock:
                            stats["skipped_error"] += 1
                    else:
                        with stats_lock:
                            stats["skipped_error"] += 1
                        if stats["skipped_error"] <= 20:
                            self.stdout.write(
                                self.style.WARNING(f"  SKIP {image.dropbox_file_name}: {error}")
                            )
                    continue

                if correct_timestamp is None:
                    with stats_lock:
                        stats["skipped_no_exif"] += 1
                    continue

                # Check if timestamp actually changed
                # Compare in UTC to avoid timezone confusion
                current_utc = image.trigger_timestamp.astimezone(pytz.utc)
                correct_utc = correct_timestamp.astimezone(pytz.utc)

                if abs((current_utc - correct_utc).total_seconds()) < 1:
                    with stats_lock:
                        stats["unchanged"] += 1
                    continue

                if dry_run and stats["updated"] < 10:
                    diff_hours = (current_utc - correct_utc).total_seconds() / 3600
                    self.stdout.write(
                        f"  {image.dropbox_file_name}: "
                        f"{image.trigger_timestamp} → {correct_timestamp} "
                        f"(diff: {diff_hours:+.1f}h)"
                    )

                image.trigger_timestamp = correct_timestamp
                images_to_update.append(image)
                with stats_lock:
                    stats["updated"] += 1

            # Bulk update
            if images_to_update and not dry_run:
                Image.objects.bulk_update(images_to_update, ["trigger_timestamp"])

            processed_total += len(batch_images)
            elapsed = time.time() - start_time
            rate = processed_total / elapsed if elapsed > 0 else 0
            eta = (total - processed_total) / rate if rate > 0 else 0

            self.stdout.write(
                f"  Batch {batch_start // batch_size + 1}: "
                f"{processed_total}/{total} processed "
                f"({stats['updated']} updated, {stats['unchanged']} unchanged, "
                f"{stats['skipped_error']} errors) "
                f"[{rate:.1f} img/s, ETA: {eta / 60:.0f}min]"
            )

        # Final summary
        elapsed = time.time() - start_time
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write(self.style.MIGRATE_HEADING("SUMMARY"))
        self.stdout.write(f"  Total processed:    {stats['processed']}")
        self.stdout.write(f"  Updated:            {stats['updated']}")
        self.stdout.write(f"  Unchanged:          {stats['unchanged']}")
        self.stdout.write(f"  Skipped (no EXIF):  {stats['skipped_no_exif']}")
        self.stdout.write(f"  Skipped (errors):   {stats['skipped_error']}")
        self.stdout.write(f"  Time elapsed:       {elapsed:.0f}s ({elapsed / 60:.1f}min)")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n  DRY RUN — no changes were saved."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n  Done. {stats['updated']} timestamps corrected."))
