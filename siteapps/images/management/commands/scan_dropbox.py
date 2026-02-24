"""
Django management command to build a Dropbox file index table.

Recursively scans all files in Dropbox and stores content_hash -> path mappings
in the dropbox_file_index table. This index is used by download_lila_images
as a fallback when files have been moved from their original paths.

Also creates the lila_download_log table for tracking relocated files.

Usage:
    # Scan entire Dropbox (default)
    uv run manage.py scan_dropbox --settings=config.settings.staging

    # Scan a specific folder
    uv run manage.py scan_dropbox --path "/2024-10-28 - point reyes" --settings=config.settings.staging

    # Rebuild from scratch (drops existing index)
    uv run manage.py scan_dropbox --drop-table --settings=config.settings.staging
"""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from siteapps.images.utils.dropbox_client import create_dropbox_client


class Command(BaseCommand):
    help = "Scan Dropbox recursively and build a content_hash -> path index table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default="",
            help='Dropbox folder path to scan (default: "" for root)',
        )
        parser.add_argument(
            "--drop-table",
            action="store_true",
            help="Drop and recreate the index table before scanning",
        )

    def handle(self, *args, **options):
        scan_path = options["path"]
        drop_table = options["drop_table"]

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        # Initialize Dropbox client
        dbx = create_dropbox_client()
        if not dbx:
            raise CommandError(
                "Dropbox credentials not configured. "
                "Make sure DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN "
                "are set in your environment."
            )

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Dropbox File Index Builder"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Scan path: {scan_path or '/ (root)'}")
        self.stdout.write("")

        # Step 1: Create tables
        self._ensure_tables(drop_table)

        # Step 2: Recursive scan
        self.stdout.write("Step 1: Scanning Dropbox recursively...")
        start_time = time.time()

        file_count = 0
        batch = []
        batch_size = 500

        result = dbx.files_list_folder(scan_path, recursive=True)

        while True:
            for entry in result.entries:
                # Only index files (not folders)
                if hasattr(entry, "content_hash") and entry.content_hash:
                    batch.append((
                        entry.content_hash,
                        entry.path_display,
                        entry.name,
                        entry.size,
                    ))
                    file_count += 1

                    if len(batch) >= batch_size:
                        self._insert_batch(batch)
                        elapsed = time.time() - start_time
                        self.stdout.write(f"  Indexed {file_count:,} files ({elapsed:.0f}s)...")
                        batch = []

            if not result.has_more:
                break

            result = dbx.files_list_folder_continue(result.cursor)

        # Insert remaining
        if batch:
            self._insert_batch(batch)

        elapsed = time.time() - start_time

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Scan Complete!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Files indexed: {file_count:,}")
        self.stdout.write(f"Time: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
        if file_count > 0:
            self.stdout.write(f"Rate: {file_count / elapsed:.0f} files/s")
        self.stdout.write("=" * 70)

    def _ensure_tables(self, drop_table):
        """Create the index and log tables."""
        with connection.cursor() as cursor:
            if drop_table:
                self.stdout.write("Dropping existing dropbox_file_index table...")
                cursor.execute("DROP TABLE IF EXISTS dropbox_file_index")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dropbox_file_index (
                    id              SERIAL PRIMARY KEY,
                    content_hash    VARCHAR(64) NOT NULL,
                    path_display    TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    size            BIGINT NOT NULL,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dbx_index_content_hash
                ON dropbox_file_index (content_hash)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lila_download_log (
                    id              SERIAL PRIMARY KEY,
                    image_id        VARCHAR(36) NOT NULL,
                    content_hash    VARCHAR(64) NOT NULL,
                    original_path   TEXT NOT NULL,
                    new_path        TEXT,
                    status          VARCHAR(20) NOT NULL,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)

        self.stdout.write(self.style.SUCCESS("Tables ready."))
        self.stdout.write("")

    def _insert_batch(self, batch):
        """Insert a batch of file entries into the index table."""
        with connection.cursor() as cursor:
            args = ",".join(
                cursor.mogrify("(%s, %s, %s, %s)", row).decode()
                for row in batch
            )
            cursor.execute(
                f"INSERT INTO dropbox_file_index (content_hash, path_display, name, size) VALUES {args}"
            )
