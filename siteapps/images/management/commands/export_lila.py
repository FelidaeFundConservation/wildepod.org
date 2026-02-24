"""
Django management command to export LILA images in parallel batches

This avoids the 7-month query planner cliff by running monthly batches
that complete in 1-2 seconds each.

Usage:
    uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31 --workers 3
    uv run manage.py export_lila --start 2023-01-01 --end 2023-12-31 --drop-table
    uv run manage.py export_lila --drop-table  # Export all images
    uv run manage.py export_lila --table lila_export_2 --drop-table --settings=config.settings.prod  # Export all images to a different table
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Export LILA images to lila_export table using parallel monthly batches"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=str,
            required=False,
            help="Start date (YYYY-MM-DD). If not provided, uses earliest image timestamp.",
        )
        parser.add_argument(
            "--end",
            type=str,
            required=False,
            help="End date (YYYY-MM-DD). If not provided, uses latest image timestamp.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=3,
            help="Number of parallel workers (default: 3)",
        )
        parser.add_argument(
            "--drop-table",
            action="store_true",
            help="Drop and recreate the lila_export table before running",
        )
        parser.add_argument(
            "--table",
            type=str,
            default="lila_export",
            help="Destination table name (default: lila_export)",
        )

    def handle(self, *args, **options):
        # Parse arguments
        start_arg = options.get("start")
        end_arg = options.get("end")

        # Use fixed defaults if not provided
        try:
            start_date = datetime.strptime(start_arg, "%Y-%m-%d") if start_arg else datetime(2020, 1, 1)
            end_date = datetime.strptime(end_arg, "%Y-%m-%d") if end_arg else datetime(2025, 12, 31, 23, 59, 59)
        except ValueError as e:
            raise CommandError(f"Invalid date format: {e}")

        if not start_arg or not end_arg:
            self.stdout.write(f"Using default date range: {start_date.date()} to {end_date.date()}\n")

        workers = options["workers"]
        drop_table = options["drop_table"]
        table_name = options["table"]

        if workers < 1 or workers > 10:
            raise CommandError("Workers must be between 1 and 10")

        # Display configuration
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("LILA Image Export"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Date range: {start_date.date()} to {end_date.date()}")
        self.stdout.write(f"Workers: {workers}")
        self.stdout.write(f"Table: {table_name}")
        self.stdout.write(f"Drop table: {drop_table}")
        self.stdout.write("=" * 60)
        self.stdout.write("")

        # Load SQL query template
        query_path = Path(__file__).parent.parent.parent.parent.parent / "scratch" / "export_lila_query.sql"
        if not query_path.exists():
            raise CommandError(f"Query file not found: {query_path}")

        with open(query_path, "r") as f:
            query_template = f.read()

        # Create table
        if drop_table:
            self._create_table(table_name)

        # Generate monthly ranges
        date_ranges = self._generate_monthly_ranges(start_date, end_date)
        self.stdout.write(f"Generated {len(date_ranges)} monthly batches\n")

        # Run parallel export
        overall_start = time.time()
        total_rows = 0
        successful = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            future_to_range = {
                executor.submit(
                    self._export_batch, query_template, start, end, table_name
                ): (start, end)
                for start, end in date_ranges
            }

            # Process completed tasks
            for future in as_completed(future_to_range):
                start, end = future_to_range[future]
                batch_name = start.strftime("%Y-%m")
                try:
                    rows_inserted, elapsed = future.result()
                    total_rows += rows_inserted
                    successful += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[{batch_name}] ✓ {rows_inserted:,} rows in {elapsed:.1f}s"
                        )
                    )
                except Exception as exc:
                    failed += 1
                    self.stdout.write(
                        self.style.ERROR(f"[{batch_name}] ✗ Error: {exc}")
                    )

        overall_elapsed = time.time() - overall_start

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("Export Complete!"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total batches: {len(date_ranges)}")
        self.stdout.write(f"Successful: {successful}")
        self.stdout.write(f"Failed: {failed}")
        self.stdout.write(f"Total rows: {total_rows:,}")
        self.stdout.write(f"Total time: {overall_elapsed:.1f}s")
        self.stdout.write(
            f"Average: {overall_elapsed/len(date_ranges):.1f}s per batch"
        )
        self.stdout.write(f"Table: {table_name}")
        self.stdout.write("=" * 60)

    def _generate_monthly_ranges(self, start_date, end_date):
        """Generate monthly date ranges between start and end dates"""
        ranges = []
        current = start_date.replace(day=1)

        while current <= end_date:
            # Start of month
            month_start = current
            # End of month
            if current.month == 12:
                month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)

            # Don't go past the end_date
            if month_end > end_date:
                month_end = end_date

            ranges.append((month_start, month_end))

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return ranges

    def _create_table(self, table_name):
        """Drop and recreate the export table"""
        self.stdout.write(f"Creating table {table_name}...")

        create_sql = f"""
        DROP TABLE IF EXISTS {table_name} CASCADE;

        CREATE TABLE {table_name} (
            id SERIAL PRIMARY KEY,
            image_id UUID NOT NULL,
            bbox_id UUID NOT NULL,
            dropbox_content_hash VARCHAR(255),
            dropbox_file_name TEXT,
            thumbnail_gcloud_path TEXT,
            dropbox_file_path TEXT,
            trigger_timestamp TIMESTAMPTZ,
            dropbox_folder_path TEXT,
            category_name VARCHAR(255),
            category_votes INTEGER,
            species_name VARCHAR(255),
            species_votes INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE INDEX idx_{table_name}_image_id ON {table_name}(image_id);
        CREATE INDEX idx_{table_name}_bbox_id ON {table_name}(bbox_id);
        CREATE INDEX idx_{table_name}_trigger_timestamp ON {table_name}(trigger_timestamp);
        CREATE INDEX idx_{table_name}_species ON {table_name}(species_name);
        """

        with connection.cursor() as cursor:
            cursor.execute(create_sql)

        self.stdout.write(self.style.SUCCESS(f"✓ Table {table_name} created\n"))

    def _export_batch(self, query_template, start_date, end_date, table_name):
        """Export a single batch to the database"""
        batch_start = time.time()

        # Build INSERT statement
        insert_sql = f"""
        INSERT INTO {table_name} (
            image_id, bbox_id, dropbox_content_hash, dropbox_file_name,
            thumbnail_gcloud_path, dropbox_file_path, trigger_timestamp,
            dropbox_folder_path, category_name, category_votes, species_name, species_votes
        )
        {query_template}
        """

        # Execute query
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    insert_sql,
                    {"start_date": start_date, "end_date": end_date},
                )
                rows_inserted = cursor.rowcount

        elapsed = time.time() - batch_start
        return rows_inserted, elapsed
