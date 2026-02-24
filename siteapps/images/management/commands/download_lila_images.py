"""
Django management command to download LILA images from Dropbox

Downloads images from Dropbox based on rows in a LILA export table.
Saves with folder structure: <output_folder>/<camera_station_id>/<year-month>/<dropbox_content_hash>.jpg
Updates the downloaded_location column in the LILA export table with the absolute path.

Processes images month-by-month (by trigger_timestamp) so that interrupted
downloads can be resumed from the last incomplete month.

Supports parallel downloads for faster processing (10 workers by default).
Automatically skips already-downloaded files for resume capability.

When a file is not found at its original Dropbox path, falls back to looking up
the content_hash in the dropbox_file_index table (built by scan_dropbox command).
Relocated files are logged to the lila_download_log table.

Usage:
    # Download all images (subfolder relative to project)
    uv run manage.py download_lila_images --table lila_export_3_sample --subfolder sample_2025

    # Download to an absolute path
    uv run manage.py download_lila_images --table lila_export_3_sample --output /data/lila/images

    # Resume from a specific month after interruption
    uv run manage.py download_lila_images --table lila_export_3_sample --output /data/lila/images --start-month 2023-06

    # Download with 20 parallel workers
    uv run manage.py download_lila_images --table lila_export_3_sample --output /data/lila/images --workers 20

    # Test with first 100 images
    uv run manage.py download_lila_images --table lila_export_3_sample --output /data/lila/test --limit 100 --workers 5

    # Dry run: check how many files can be found in Dropbox (via dropbox_file_index)
    uv run manage.py download_lila_images --table lila_export_3_sample --dry-run

Performance:
    - 1 worker: ~1.0s per image
    - 10 workers: ~0.1s per image (10x faster)
    - 20 workers: ~0.05s per image (20x faster)

    For 300k images:
    - 1 worker: ~87 hours
    - 10 workers: ~8-9 hours
    - 20 workers: ~4-5 hours
"""
import errno
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import dropbox.exceptions
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from siteapps.images.utils.dropbox_client import create_dropbox_client


class Command(BaseCommand):
    help = "Download LILA images from Dropbox based on export table"

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
        parser.add_argument(
            "--start-month",
            type=str,
            default=None,
            help="Resume from this month, skipping earlier months (format: YYYY-MM, e.g., 2023-06)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of images to download (for testing)",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=10,
            help="Number of parallel download workers (default: 10, recommended: 10-20)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check how many files from the table can be found in Dropbox (via dropbox_file_index). No downloads.",
        )

    def handle(self, *args, **options):
        table_name = options["table"]
        subfolder = options["subfolder"]
        output = options["output"]
        start_month = options["start_month"]
        limit = options["limit"]
        workers = options["workers"]
        dry_run = options["dry_run"]

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        if dry_run:
            return self._handle_dry_run(table_name)

        if not subfolder and not output:
            raise CommandError("You must specify either --subfolder or --output.")
        if subfolder and output:
            raise CommandError("Use either --subfolder or --output, not both.")

        # Setup output directory
        if output:
            output_dir = Path(output)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
            output_dir = base_dir / "lila" / subfolder

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise CommandError(f"Permission denied: Cannot create output directory '{output_dir}'")
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise CommandError(f"No space left on device: Cannot create output directory '{output_dir}'")
            elif e.errno == errno.EROFS:
                raise CommandError(f"Read-only file system: Cannot create output directory '{output_dir}'")
            else:
                raise CommandError(f"Failed to create output directory '{output_dir}': {e}")

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("LILA Image Download from Dropbox"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {table_name}")
        self.stdout.write(f"Output directory: {output_dir}")
        self.stdout.write(f"Start month: {start_month or 'beginning'}")
        self.stdout.write(f"Limit: {limit or 'None (all images)'}")
        self.stdout.write(f"Workers: {workers}")
        self.stdout.write("=" * 70)
        self.stdout.write("")

        # Initialize Dropbox client
        dbx = create_dropbox_client()
        if not dbx:
            raise CommandError(
                "Dropbox credentials not configured. "
                "Make sure DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN "
                "are set in your environment."
            )

        # Step 1: Get images to download, grouped by month
        self.stdout.write("Step 1: Querying database for images...")
        images = self._get_images_to_download(table_name, limit)
        self.stdout.write(f"  Found {len(images):,} unique images to download")

        months = self._group_by_month(images)
        month_keys = list(months.keys())
        self.stdout.write(f"  Spanning {len(month_keys)} months: {month_keys[0]} to {month_keys[-1]}")

        # Apply --start-month filter
        if start_month:
            month_keys = [m for m in month_keys if m >= start_month]
            if not month_keys:
                raise CommandError(f"No months found at or after {start_month}")
            skipped_count = len(months) - len(month_keys)
            self.stdout.write(f"  Resuming from {start_month} ({skipped_count} earlier months skipped)")

        total_images = sum(len(months[m]) for m in month_keys)
        self.stdout.write(f"  Images to process: {total_images:,}")
        self.stdout.write("")

        # Step 2: Download month by month
        self.stdout.write("Step 2: Downloading images month by month...")
        self.stdout.write("")

        overall_stats = {
            "total": total_images,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "hash_mismatch": 0,
            "relocated": 0,
        }
        overall_start = time.time()

        for i, month_key in enumerate(month_keys, 1):
            month_images = months[month_key]
            self.stdout.write(f"[{month_key}] Starting ({i}/{len(month_keys)}) - {len(month_images):,} images...")

            month_stats = self._download_month(dbx, month_images, output_dir, table_name, workers)

            # Accumulate into overall stats
            overall_stats["downloaded"] += month_stats["downloaded"]
            overall_stats["skipped"] += month_stats["skipped"]
            overall_stats["failed"] += month_stats["failed"]
            overall_stats["hash_mismatch"] += month_stats["hash_mismatch"]
            overall_stats["relocated"] += month_stats.get("relocated", 0)

            # Month completion message
            self.stdout.write(
                self.style.SUCCESS(
                    f"[{month_key}] COMPLETE - "
                    f"Downloaded: {month_stats['downloaded']:,} | "
                    f"Skipped: {month_stats['skipped']:,} | "
                    f"Failed: {month_stats['failed']:,} | "
                    f"Time: {month_stats['elapsed']:.1f}s"
                )
            )
            self.stdout.write("")

        overall_elapsed = time.time() - overall_start

        # Step 3: Summary
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Download Complete!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Months processed: {len(month_keys)} ({month_keys[0]} to {month_keys[-1]})")
        self.stdout.write(f"Total images: {overall_stats['total']:,}")
        self.stdout.write(self.style.SUCCESS(f"Downloaded: {overall_stats['downloaded']:,}"))
        self.stdout.write(f"Skipped (already exists): {overall_stats['skipped']:,}")
        if overall_stats["relocated"] > 0:
            self.stdout.write(f"Relocated (via dropbox_file_index): {overall_stats['relocated']:,}")
        self.stdout.write(self.style.ERROR(f"Failed: {overall_stats['failed']:,}"))
        self.stdout.write(f"  - Hash verification failures: {overall_stats['hash_mismatch']:,}")
        self.stdout.write(f"Total time: {overall_elapsed:.1f}s ({overall_elapsed/60:.1f} min)")
        if overall_stats["downloaded"] > 0:
            self.stdout.write(f"Download rate: {overall_stats['downloaded']/overall_elapsed:.2f} images/s")
            self.stdout.write(f"Average: {overall_elapsed/overall_stats['downloaded']:.2f}s per image")
        self.stdout.write("=" * 70)

    def _handle_dry_run(self, table_name):
        """Check how many files from the LILA table can be found in the dropbox_file_index."""
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("LILA Download - Dry Run"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {table_name}")
        self.stdout.write("")

        with connection.cursor() as cursor:
            # Check that dropbox_file_index exists and has data
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'dropbox_file_index'"
            )
            if cursor.fetchone()[0] == 0:
                raise CommandError(
                    "dropbox_file_index table does not exist. Run scan_dropbox first."
                )

            cursor.execute("SELECT COUNT(*) FROM dropbox_file_index")
            index_count = cursor.fetchone()[0]
            self.stdout.write(f"Dropbox file index: {index_count:,} files")
            self.stdout.write("")

            # Total unique images in LILA table
            cursor.execute(f"""
                SELECT COUNT(DISTINCT dropbox_content_hash)
                FROM {table_name}
                WHERE dropbox_content_hash IS NOT NULL
            """)
            total = cursor.fetchone()[0]
            self.stdout.write(f"Unique images in {table_name}: {total:,}")

            # How many have a match in dropbox_file_index
            cursor.execute(f"""
                SELECT COUNT(DISTINCT le.dropbox_content_hash)
                FROM {table_name} le
                INNER JOIN dropbox_file_index dfi
                    ON le.dropbox_content_hash = dfi.content_hash
                WHERE le.dropbox_content_hash IS NOT NULL
            """)
            found = cursor.fetchone()[0]
            missing = total - found
            pct = (found / total * 100) if total > 0 else 0

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Found in Dropbox:   {found:,} ({pct:.1f}%)"))
            self.stdout.write(self.style.ERROR(f"Missing in Dropbox: {missing:,} ({100 - pct:.1f}%)"))

            # Breakdown by month
            self.stdout.write("")
            self.stdout.write("Breakdown by month:")
            self.stdout.write(f"  {'Month':<10} {'Total':>8} {'Found':>8} {'Missing':>8} {'%':>7}")
            self.stdout.write("  " + "-" * 45)

            cursor.execute(f"""
                SELECT
                    to_char(le.trigger_timestamp, 'YYYY-MM') AS month,
                    COUNT(DISTINCT le.dropbox_content_hash) AS total,
                    COUNT(DISTINCT CASE WHEN dfi.content_hash IS NOT NULL
                        THEN le.dropbox_content_hash END) AS found
                FROM {table_name} le
                LEFT JOIN dropbox_file_index dfi
                    ON le.dropbox_content_hash = dfi.content_hash
                WHERE le.dropbox_content_hash IS NOT NULL
                  AND le.trigger_timestamp IS NOT NULL
                GROUP BY month
                ORDER BY month
            """)

            for row in cursor.fetchall():
                month, m_total, m_found = row
                m_missing = m_total - m_found
                m_pct = (m_found / m_total * 100) if m_total > 0 else 0
                style = self.style.SUCCESS if m_missing == 0 else self.style.ERROR
                self.stdout.write(style(
                    f"  {month:<10} {m_total:>8,} {m_found:>8,} {m_missing:>8,} {m_pct:>6.1f}%"
                ))

        self.stdout.write("=" * 70)

    def _get_images_to_download(self, table_name, limit):
        """
        Get unique images from table ordered by trigger_timestamp.
        Returns list of dicts with image_id, dropbox_file_path, dropbox_content_hash,
        thumbnail_gcloud_path, species_name, trigger_month, camera_station_id.
        """
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = f"""
        SELECT * FROM (
            SELECT DISTINCT ON (image_id)
                image_id,
                dropbox_file_path,
                dropbox_content_hash,
                thumbnail_gcloud_path,
                species_name,
                to_char(trigger_timestamp, 'YYYY-MM') AS trigger_month,
                camera_station_id
            FROM {table_name}
            WHERE dropbox_file_path IS NOT NULL
              AND dropbox_content_hash IS NOT NULL
              AND trigger_timestamp IS NOT NULL
            ORDER BY image_id, id
        ) sub
        ORDER BY trigger_month, image_id
        {limit_clause}
        """

        images = []
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                images.append(dict(zip(columns, row)))

        return images

    def _group_by_month(self, images):
        """Group images into an OrderedDict keyed by YYYY-MM."""
        months = OrderedDict()
        for image in images:
            month_key = image["trigger_month"]
            if month_key not in months:
                months[month_key] = []
            months[month_key].append(image)
        return months

    def _verify_hash(self, dropbox_content_hash, thumbnail_gcloud_path):
        """
        Verify that dropbox_content_hash matches the hash in thumbnail_gcloud_path

        Example thumbnail_gcloud_path:
        thumbnails/1024/b35cbf9f878a8d05854fe51db3a95e441dcb8c34031f3f5afe188a14a2af77cf.jpg

        Extract: b35cbf9f878a8d05854fe51db3a95e441dcb8c34031f3f5afe188a14a2af77cf
        """
        if not thumbnail_gcloud_path:
            return False  # Can't verify, treat as failure

        # Extract filename from path
        filename = Path(thumbnail_gcloud_path).stem  # Remove .jpg
        expected_hash = filename

        if dropbox_content_hash != expected_hash:
            return False

        return True

    def _download_single_image(self, dbx, image, output_dir, table_name, stats, stats_lock):
        """Download a single image from Dropbox (worker function for parallel execution)"""
        image_id = image["image_id"]
        dropbox_path = image["dropbox_file_path"]
        content_hash = image["dropbox_content_hash"]
        thumbnail_path = image["thumbnail_gcloud_path"]
        species_name = image["species_name"]
        camera_station_id = image["camera_station_id"]
        trigger_month = image["trigger_month"]

        result = {"status": "success", "message": ""}

        # Verify hash
        if not self._verify_hash(content_hash, thumbnail_path):
            with stats_lock:
                stats["hash_mismatch"] += 1
                stats["failed"] += 1
                stats["processed"] += 1
            result["status"] = "hash_mismatch"
            result["message"] = f"✗ {species_name:40s} Hash verification failed - image_id: {image_id}"
            return result

        # Create folder structure: output_dir/camera_station_id/year-month/
        image_subdir = output_dir / str(camera_station_id) / trigger_month
        try:
            image_subdir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            result["status"] = "error"
            result["message"] = f"✗ {species_name:40s} Permission denied creating directory: {image_subdir}"
            return result
        except OSError as e:
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            if e.errno == errno.ENOSPC:
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} No space left on device: {image_subdir}"
            elif e.errno == errno.EROFS:
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} Read-only file system: {image_subdir}"
            else:
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} Failed to create directory: {image_subdir} - {e}"
            return result

        # Output filename
        output_file = image_subdir / f"{content_hash}.jpg"

        # Skip if exists (with I/O error handling)
        try:
            file_exists = output_file.exists()
        except OSError as e:
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            if e.errno == errno.EIO:
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} I/O error checking file: {output_file}"
            else:
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} Error checking file: {output_file} - {e}"
            return result

        if file_exists:
            # Update downloaded_location even for skipped files (in case it wasn't set before)
            self._update_downloaded_location(table_name, image_id, str(output_file.resolve()))
            with stats_lock:
                stats["skipped"] += 1
                stats["processed"] += 1
            result["status"] = "skipped"
            return result

        # Download from Dropbox
        try:
            # Add leading slash if not present
            if not dropbox_path.startswith("/"):
                dropbox_path = "/" + dropbox_path

            metadata, response = dbx.files_download(dropbox_path)

            # Save file with explicit error handling
            try:
                with open(output_file, "wb") as f:
                    f.write(response.content)
            except PermissionError:
                with stats_lock:
                    stats["failed"] += 1
                    stats["processed"] += 1
                result["status"] = "error"
                result["message"] = f"✗ {species_name:40s} Permission denied writing file: {output_file}"
                return result
            except OSError as e:
                with stats_lock:
                    stats["failed"] += 1
                    stats["processed"] += 1
                if e.errno == errno.ENOSPC:
                    result["status"] = "error"
                    result["message"] = f"✗ {species_name:40s} No space left on device: {output_file}"
                elif e.errno == errno.EROFS:
                    result["status"] = "error"
                    result["message"] = f"✗ {species_name:40s} Read-only file system: {output_file}"
                elif e.errno == errno.EIO:
                    result["status"] = "error"
                    result["message"] = f"✗ {species_name:40s} I/O error writing file: {output_file}"
                else:
                    result["status"] = "error"
                    result["message"] = f"✗ {species_name:40s} Failed to write file: {output_file} - {e}"
                # Clean up partial file if it exists
                try:
                    if output_file.exists():
                        output_file.unlink()
                except OSError:
                    pass
                return result

            # Update downloaded_location in the database
            self._update_downloaded_location(table_name, image_id, str(output_file.resolve()))

            with stats_lock:
                stats["downloaded"] += 1
                stats["processed"] += 1
            result["status"] = "downloaded"
            result["message"] = f"✓ {species_name:40s} {content_hash}.jpg"
            return result

        except dropbox.exceptions.ApiError as e:
            # On path-not-found, try the dropbox_file_index lookup
            if self._is_not_found_error(e):
                return self._fallback_download(
                    dbx, image, dropbox_path, output_file, table_name, stats, stats_lock
                )

            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            result["status"] = "failed"
            result["message"] = f"✗ {species_name:40s} Failed: {dropbox_path} - image_id: {image_id} - {e}"
            return result
        except Exception as e:
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            result["status"] = "error"
            result["message"] = f"✗ {species_name:40s} Error: {dropbox_path} - image_id: {image_id} - {e}"
            return result

    def _is_not_found_error(self, api_error):
        """Check if a Dropbox ApiError is a path-not-found error."""
        try:
            return api_error.error.is_path() and api_error.error.get_path().is_not_found()
        except Exception:
            return False

    def _fallback_download(self, dbx, image, original_path, output_file, table_name, stats, stats_lock):
        """Look up content_hash in dropbox_file_index table and download from new path."""
        image_id = image["image_id"]
        content_hash = image["dropbox_content_hash"]
        species_name = image["species_name"]
        result = {"status": "failed", "message": ""}

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT path_display FROM dropbox_file_index WHERE content_hash = %s LIMIT 1",
                    [content_hash],
                )
                row = cursor.fetchone()

            if row:
                new_path = row[0]
                _, response = dbx.files_download(new_path)

                # Save file with explicit error handling
                try:
                    with open(output_file, "wb") as f:
                        f.write(response.content)
                except PermissionError:
                    with stats_lock:
                        stats["failed"] += 1
                        stats["processed"] += 1
                    result["status"] = "error"
                    result["message"] = f"✗ {species_name:40s} Permission denied writing file: {output_file}"
                    return result
                except OSError as e:
                    with stats_lock:
                        stats["failed"] += 1
                        stats["processed"] += 1
                    if e.errno == errno.ENOSPC:
                        result["status"] = "error"
                        result["message"] = f"✗ {species_name:40s} No space left on device: {output_file}"
                    elif e.errno == errno.EROFS:
                        result["status"] = "error"
                        result["message"] = f"✗ {species_name:40s} Read-only file system: {output_file}"
                    elif e.errno == errno.EIO:
                        result["status"] = "error"
                        result["message"] = f"✗ {species_name:40s} I/O error writing file: {output_file}"
                    else:
                        result["status"] = "error"
                        result["message"] = f"✗ {species_name:40s} Failed to write file: {output_file} - {e}"
                    # Clean up partial file if it exists
                    try:
                        if output_file.exists():
                            output_file.unlink()
                    except OSError:
                        pass
                    return result

                # Log the relocation
                self._log_relocation(image_id, content_hash, original_path, new_path)

                # Update downloaded_location in the database
                self._update_downloaded_location(table_name, image_id, str(output_file.resolve()))

                with stats_lock:
                    stats["downloaded"] += 1
                    stats["relocated"] += 1
                    stats["processed"] += 1
                result["status"] = "relocated"
                result["message"] = f"↻ {species_name:40s} {content_hash}.jpg (relocated: {new_path})"
                return result

        except dropbox.exceptions.ApiError:
            pass  # Fall through to failure below
        except Exception:
            pass  # Fall through to failure below for other errors

        # No match in index or index doesn't exist
        self._log_relocation(image_id, content_hash, original_path, None)

        with stats_lock:
            stats["failed"] += 1
            stats["processed"] += 1
        result["message"] = f"✗ {species_name:40s} Not found: {original_path} - image_id: {image_id}"
        return result

    def _log_relocation(self, image_id, content_hash, original_path, new_path):
        """Log a relocated or missing file to lila_download_log."""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO lila_download_log
                        (image_id, content_hash, original_path, new_path, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    [
                        str(image_id),
                        content_hash,
                        original_path,
                        new_path,
                        "relocated" if new_path else "not_found",
                    ],
                )
        except Exception:
            pass  # Don't fail the download over logging

    def _update_downloaded_location(self, table_name, image_id, downloaded_location):
        """Update the downloaded_location column in the LILA export table."""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {table_name}
                    SET downloaded_location = %s
                    WHERE image_id = %s
                    """,
                    [downloaded_location, str(image_id)],
                )
        except Exception:
            pass  # Don't fail the download over database update

    def _download_month(self, dbx, images, output_dir, table_name, workers):
        """Download a single month's images from Dropbox in parallel."""
        stats = {
            "total": len(images),
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "hash_mismatch": 0,
            "relocated": 0,
            "processed": 0,
        }
        stats_lock = Lock()
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_image = {
                executor.submit(self._download_single_image, dbx, image, output_dir, table_name, stats, stats_lock): image
                for image in images
            }

            for future in as_completed(future_to_image):
                result = future.result()

                if result["status"] in ["downloaded", "relocated", "hash_mismatch", "failed", "error"]:
                    if result["status"] == "downloaded":
                        self.stdout.write(self.style.SUCCESS(result["message"]))
                    elif result["status"] == "relocated":
                        self.stdout.write(self.style.WARNING(result["message"]))
                    else:
                        self.stdout.write(self.style.ERROR(result["message"]))

        stats["elapsed"] = time.time() - start_time
        return stats
