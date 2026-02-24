"""
Django management command to check LILA download progress.

Queries the LILA export table for files ordered by trigger_timestamp,
then uses binary search to find the last downloaded file in a given folder.
Displays the last 10 downloaded files with their sizes and timestamps.

Usage:
    # Check download progress (subfolder)
    uv run manage.py check_lila_download --table lila_export_3_sample --subfolder sample_2025

    # Check with absolute path
    uv run manage.py check_lila_download --table lila_export_3_sample --output /data/lila/images
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Check LILA download progress using binary search to find the last downloaded file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            type=str,
            required=True,
            help="Source table name (e.g., lila_export_3_sample)",
        )
        parser.add_argument(
            "--subfolder",
            type=str,
            help="Subfolder name under ../lila/ (e.g., sample_2025)",
        )
        parser.add_argument(
            "--output",
            type=str,
            help="Absolute path to output directory (alternative to --subfolder)",
        )

    def handle(self, *args, **options):
        table_name = options["table"]
        subfolder = options["subfolder"]
        output = options["output"]

        if not subfolder and not output:
            raise CommandError("You must specify either --subfolder or --output.")
        if subfolder and output:
            raise CommandError("Use either --subfolder or --output, not both.")

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        # Resolve output directory
        if output:
            output_dir = Path(output)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
            output_dir = base_dir / "lila" / subfolder

        if not output_dir.exists():
            raise CommandError(f"Output directory does not exist: {output_dir}")

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("LILA Download Progress Check"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {table_name}")
        self.stdout.write(f"Output directory: {output_dir}")
        self.stdout.write("")

        # Step 1: Get ordered file list from DB
        self.stdout.write("Step 1: Querying database for ordered file list...")
        files = self._get_ordered_files(table_name)
        total = len(files)
        self.stdout.write(f"  Found {total:,} unique images ordered by trigger_timestamp")
        if total == 0:
            self.stdout.write(self.style.WARNING("  No images found in table."))
            return
        self.stdout.write(f"  Date range: {files[0]['trigger_timestamp']} to {files[-1]['trigger_timestamp']}")
        self.stdout.write("")

        # Step 2: Binary search for last downloaded file
        self.stdout.write("Step 2: Binary searching for last downloaded file...")
        last_idx = self._binary_search_last_downloaded(files, output_dir)

        if last_idx == -1:
            self.stdout.write(self.style.WARNING("  No downloaded files found in the output directory."))
            first_path = self._build_file_path(output_dir, files[0])
            self.stdout.write(f"  First file to download: {first_path.relative_to(output_dir)}")
            self.stdout.write(f"  Trigger timestamp: {files[0]['trigger_timestamp']}")
            return

        downloaded_count = last_idx + 1
        remaining = total - downloaded_count
        progress_pct = (downloaded_count / total) * 100

        self.stdout.write(f"  Last downloaded file index: {last_idx} / {total - 1}")
        self.stdout.write(f"  Downloaded: {downloaded_count:,} / {total:,} ({progress_pct:.1f}%)")
        self.stdout.write(f"  Remaining: {remaining:,}")
        self.stdout.write("")

        # Step 3: Show the resume month
        last_file = files[last_idx]
        last_month = str(last_file["trigger_timestamp"])[:7]  # YYYY-MM
        self.stdout.write(f"  Last active month: {last_month}")
        self.stdout.write("")
        self.stdout.write(f"  To resume: --start-month {last_month}")
        self.stdout.write("=" * 70)

    def _get_ordered_files(self, table_name):
        """Get unique images ordered by trigger_timestamp."""
        query = f"""
        SELECT DISTINCT ON (image_id)
            image_id,
            dropbox_content_hash,
            trigger_timestamp,
            camera_station_id,
            to_char(trigger_timestamp, 'YYYY-MM') AS trigger_month
        FROM {table_name}
        WHERE dropbox_file_path IS NOT NULL
          AND dropbox_content_hash IS NOT NULL
          AND trigger_timestamp IS NOT NULL
        ORDER BY image_id, id
        """

        # Wrap to re-order by trigger_timestamp
        query = f"""
        SELECT image_id, dropbox_content_hash, trigger_timestamp, camera_station_id, trigger_month
        FROM ({query}) sub
        ORDER BY trigger_timestamp, image_id
        """

        files = []
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                files.append(dict(zip(columns, row)))

        return files

    def _build_file_path(self, output_dir, file_info):
        """Build file path with folder structure: camera_station_id/YYYY-MM/hash.jpg"""
        camera_station = str(file_info["camera_station_id"]) if file_info.get("camera_station_id") else "unknown"
        trigger_month = file_info.get("trigger_month") or "unknown"
        return output_dir / camera_station / trigger_month / f"{file_info['dropbox_content_hash']}.jpg"

    def _binary_search_last_downloaded(self, files, output_dir):
        """
        Binary search to find the index of the last contiguously downloaded file.

        Assumes downloads happen in order (by trigger_timestamp). Finds the
        boundary where files transition from existing to not-existing on disk.

        Returns the index of the last downloaded file, or -1 if none found.
        """
        n = len(files)

        # Quick check: if first file doesn't exist, nothing downloaded
        first_file = self._build_file_path(output_dir, files[0])
        if not first_file.exists():
            return -1

        # Quick check: if last file exists, everything is downloaded
        last_file = self._build_file_path(output_dir, files[-1])
        if last_file.exists():
            return n - 1

        # Binary search: find the last index where file exists
        lo, hi = 0, n - 1
        result = 0

        while lo <= hi:
            mid = (lo + hi) // 2
            filepath = self._build_file_path(output_dir, files[mid])
            if filepath.exists():
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1

        return result

