# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Create and populate a tracking table for the Bhutan timestamp fix.

Pass 1: Creates bhutan_timestamp_fix table and inserts a row per image (fast, no Dropbox).
Pass 2: Downloads EXIF headers from Dropbox and populates exif_timestamp (resumable).

Usage:
    # Full run (both passes)
    python manage.py populate_exif_timestamps --settings=config.settings.bhutan

    # Resume (skip Pass 1, continue EXIF downloads)
    python manage.py populate_exif_timestamps --skip-populate --settings=config.settings.bhutan

    # Test with a small sample
    python manage.py populate_exif_timestamps --limit 20 --settings=config.settings.bhutan
"""

import concurrent.futures
import logging
import time

import pytz
from django.core.management.base import BaseCommand
from django.db import connection
from images.utils.dropbox_client import create_dropbox_client

from .fix_bhutan_timestamps import BHUTAN_TZ, download_exif_via_temp_link

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bhutan_timestamp_fix (
    image_id UUID PRIMARY KEY REFERENCES images_image(id),
    upload_id UUID NOT NULL REFERENCES images_upload(id),
    dropbox_path TEXT NOT NULL,
    current_trigger_timestamp TIMESTAMPTZ NOT NULL,
    exif_timestamp TIMESTAMPTZ,
    exif_error TEXT,
    has_time_correction BOOLEAN NOT NULL DEFAULT FALSE,
    time_correction_applied BOOLEAN NOT NULL DEFAULT FALSE,
    timezone_fix_applied BOOLEAN NOT NULL DEFAULT FALSE
);
"""

CREATE_INDEXES_SQL = [
    """
    CREATE INDEX IF NOT EXISTS idx_bhutan_ts_fix_pending
        ON bhutan_timestamp_fix (image_id)
        WHERE exif_timestamp IS NULL AND exif_error IS NULL;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bhutan_ts_fix_upload
        ON bhutan_timestamp_fix (upload_id);
    """,
]

POPULATE_SQL = """
INSERT INTO bhutan_timestamp_fix (
    image_id, upload_id, dropbox_path, current_trigger_timestamp,
    has_time_correction, time_correction_applied
)
SELECT
    i.id,
    i.upload_id,
    i.dropbox_file_path,
    i.trigger_timestamp,
    (u.time_correction_id IS NOT NULL),
    i.time_correction_applied
FROM images_image i
JOIN images_upload u ON i.upload_id = u.id
WHERE i.trigger_timestamp IS NOT NULL
    AND i.deleted = FALSE
ON CONFLICT (image_id) DO NOTHING;
"""

POPULATE_FILTERED_SQL = """
INSERT INTO bhutan_timestamp_fix (
    image_id, upload_id, dropbox_path, current_trigger_timestamp,
    has_time_correction, time_correction_applied
)
SELECT
    i.id,
    i.upload_id,
    i.dropbox_file_path,
    i.trigger_timestamp,
    (u.time_correction_id IS NOT NULL),
    i.time_correction_applied
FROM images_image i
JOIN images_upload u ON i.upload_id = u.id
JOIN locations_camerastation cs ON u.camera_station_id = cs.id
WHERE i.trigger_timestamp IS NOT NULL
    AND i.deleted = FALSE
    AND cs.station_id ILIKE %s
ON CONFLICT (image_id) DO NOTHING;
"""

PENDING_QUERY = """
SELECT image_id, dropbox_path
FROM bhutan_timestamp_fix
WHERE exif_timestamp IS NULL AND exif_error IS NULL AND dropbox_path != ''
"""

PENDING_FILTERED_QUERY = """
SELECT f.image_id, f.dropbox_path
FROM bhutan_timestamp_fix f
JOIN images_upload u ON f.upload_id = u.id
JOIN locations_camerastation cs ON u.camera_station_id = cs.id
WHERE f.exif_timestamp IS NULL AND f.exif_error IS NULL AND f.dropbox_path != ''
    AND cs.station_id ILIKE %s
"""

PENDING_UPLOAD_QUERY = """
SELECT image_id, dropbox_path
FROM bhutan_timestamp_fix
WHERE exif_timestamp IS NULL AND exif_error IS NULL AND dropbox_path != ''
    AND upload_id = %s
"""

MAX_DOWNLOAD_THREADS = 10


class Command(BaseCommand):
    help = "Create and populate the bhutan_timestamp_fix tracking table with EXIF timestamps."

    def add_arguments(self, parser):
        parser.add_argument(
            "--camera-station",
            type=str,
            default=None,
            help="Filter by camera station ID (substring match).",
        )
        parser.add_argument(
            "--upload-id",
            type=str,
            default=None,
            help="Filter to a specific upload UUID.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Images per batch in Pass 2 (default: 500).",
        )
        parser.add_argument(
            "--threads",
            type=int,
            default=MAX_DOWNLOAD_THREADS,
            help=f"Parallel Dropbox download threads (default: {MAX_DOWNLOAD_THREADS}).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap total images to process in Pass 2 (for testing).",
        )
        parser.add_argument(
            "--skip-populate",
            action="store_true",
            help="Skip Pass 1 (table creation/row insertion), go straight to EXIF downloads.",
        )

    def handle(self, *args, **options):
        camera_station = options["camera_station"]
        upload_id = options["upload_id"]
        batch_size = options["batch_size"]
        threads = options["threads"]
        limit = options["limit"]
        skip_populate = options["skip_populate"]

        if not skip_populate:
            self._pass1_create_and_populate(camera_station, upload_id)

        self._pass2_download_exif(camera_station, upload_id, batch_size, threads, limit)

    def _pass1_create_and_populate(self, camera_station, upload_id):
        """Create the tracking table and insert rows for all Bhutan images."""
        self.stdout.write("Pass 1: Creating table and inserting rows...")

        with connection.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDEXES_SQL:
                cursor.execute(idx_sql)

            if upload_id:
                cursor.execute(
                    POPULATE_FILTERED_SQL.replace(
                        "AND cs.station_id ILIKE %s", "AND u.id = %s"
                    ).replace(
                        "JOIN locations_camerastation cs ON u.camera_station_id = cs.id\n", ""
                    ),
                    [upload_id],
                )
            elif camera_station:
                cursor.execute(POPULATE_FILTERED_SQL, [f"%{camera_station}%"])
            else:
                cursor.execute(POPULATE_SQL)

            inserted = cursor.rowcount
            self.stdout.write(f"  Inserted {inserted} rows.")

            cursor.execute("SELECT COUNT(*) FROM bhutan_timestamp_fix")
            total = cursor.fetchone()[0]
            self.stdout.write(f"  Total rows in table: {total}")

    def _pass2_download_exif(self, camera_station, upload_id, batch_size, threads, limit):
        """Download EXIF headers from Dropbox and populate exif_timestamp."""
        dbx = create_dropbox_client()
        if dbx is None:
            self.stderr.write(self.style.ERROR("Could not create Dropbox client."))
            return

        # Get pending count
        with connection.cursor() as cursor:
            if upload_id:
                cursor.execute(PENDING_UPLOAD_QUERY.replace("SELECT image_id, dropbox_path", "SELECT COUNT(*)"), [upload_id])
            elif camera_station:
                cursor.execute(PENDING_FILTERED_QUERY.replace("SELECT f.image_id, f.dropbox_path", "SELECT COUNT(*)"), [f"%{camera_station}%"])
            else:
                cursor.execute(PENDING_QUERY.replace("SELECT image_id, dropbox_path", "SELECT COUNT(*)"))
            total_pending = cursor.fetchone()[0]

        if total_pending == 0:
            self.stdout.write(self.style.SUCCESS("Pass 2: No pending rows. All EXIF timestamps populated."))
            return

        target = min(total_pending, limit) if limit else total_pending
        self.stdout.write(f"Pass 2: {total_pending} rows pending EXIF download. Processing {target}.")
        self.stdout.write(f"  Using {threads} threads, batch size {batch_size}.\n")

        stats = {"populated": 0, "errors": 0, "processed": 0}
        start_time = time.time()

        while stats["processed"] < target:
            # Fetch next batch (always re-query since processed rows drop out of the pending set)
            remaining = target - stats["processed"]
            fetch_size = min(batch_size, remaining)

            with connection.cursor() as cursor:
                if upload_id:
                    cursor.execute(PENDING_UPLOAD_QUERY + f" LIMIT {fetch_size}", [upload_id])
                elif camera_station:
                    cursor.execute(PENDING_FILTERED_QUERY + f" LIMIT {fetch_size}", [f"%{camera_station}%"])
                else:
                    cursor.execute(PENDING_QUERY + f" LIMIT {fetch_size}")
                rows = cursor.fetchall()

            if not rows:
                break

            # Download EXIF in parallel
            results = []

            def process_row(row):
                image_id, dropbox_path = row
                exif_dt, error = download_exif_via_temp_link(dbx, dropbox_path)
                if exif_dt:
                    return image_id, BHUTAN_TZ.localize(exif_dt), None
                return image_id, None, error or "no EXIF DateTimeOriginal"

            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
                futures = {executor.submit(process_row, row): row for row in rows}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        row = futures[future]
                        results.append((row[0], None, str(e)))

            # Batch update results
            with connection.cursor() as cursor:
                for image_id, exif_ts, error in results:
                    if exif_ts:
                        cursor.execute(
                            "UPDATE bhutan_timestamp_fix SET exif_timestamp = %s WHERE image_id = %s",
                            [exif_ts, image_id],
                        )
                        stats["populated"] += 1
                    else:
                        cursor.execute(
                            "UPDATE bhutan_timestamp_fix SET exif_error = %s WHERE image_id = %s",
                            [error[:500] if error else "unknown error", image_id],
                        )
                        stats["errors"] += 1

            stats["processed"] += len(rows)

            elapsed = time.time() - start_time
            rate = stats["processed"] / elapsed if elapsed > 0 else 0
            eta = (target - stats["processed"]) / rate if rate > 0 else 0

            self.stdout.write(
                f"  {stats['processed']}/{target} processed "
                f"({stats['populated']} populated, {stats['errors']} errors) "
                f"[{rate:.1f} img/s, ETA: {eta / 60:.0f}min]"
            )

        elapsed = time.time() - start_time
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write(self.style.MIGRATE_HEADING("SUMMARY"))
        self.stdout.write(f"  Processed:    {stats['processed']}")
        self.stdout.write(f"  Populated:    {stats['populated']}")
        self.stdout.write(f"  Errors:       {stats['errors']}")
        self.stdout.write(f"  Time:         {elapsed:.0f}s ({elapsed / 60:.1f}min)")

        # Show remaining
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM bhutan_timestamp_fix WHERE exif_timestamp IS NULL AND exif_error IS NULL")
            still_pending = cursor.fetchone()[0]
        if still_pending:
            self.stdout.write(self.style.WARNING(f"  Still pending: {still_pending} (re-run to continue)"))
        else:
            self.stdout.write(self.style.SUCCESS("  All EXIF timestamps populated!"))
