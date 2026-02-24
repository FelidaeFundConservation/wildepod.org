"""
Django management command to verify LILA images against database rows.

Checks output directory against table rows and optionally:
- Removes rows where files are missing (--remove-missing)
- Updates downloaded_location column with file paths (--update-downloaded-location)

Usage:
    # Just verify (no changes)
    uv run manage.py verify_lila_images --table lila_export_3_sampleE --output-dir ../lila/sample_E --settings=config.settings.prod

    # Remove rows with missing files
    uv run manage.py verify_lila_images --table lila_export_3_sampleE --output-dir ../lila/sample_E --remove-missing --settings=config.settings.prod

    # Update downloaded_location column for existing files
    uv run manage.py verify_lila_images --table lila_export_3_sampleE --output-dir ../lila/sample_E --update-downloaded-location --settings=config.settings.prod

    # Both operations
    uv run manage.py verify_lila_images --table lila_export_3_sampleE --output-dir ../lila/sample_E --remove-missing --update-downloaded-location --settings=config.settings.prod
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verify LILA images exist and optionally remove missing rows or update downloaded locations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            type=str,
            required=True,
            help="Source table name (e.g., lila_export_3_sample)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            required=True,
            help="Path to image directory (e.g., ../lila/sample_2025)",
        )
        parser.add_argument(
            "--remove-missing",
            action="store_true",
            help="Remove table rows that don't have corresponding downloaded files",
        )
        parser.add_argument(
            "--update-downloaded-location",
            action="store_true",
            help="Update downloaded_location column with file path for existing files",
        )

    def handle(self, *args, **options):
        table_name = options["table"]
        image_dir = Path(options["output_dir"]).resolve()
        remove_missing = options["remove_missing"]
        update_location = options["update_downloaded_location"]

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        if not image_dir.exists():
            raise CommandError(f"Directory does not exist: {image_dir}")

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Verify LILA Images"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Table: {table_name}")
        self.stdout.write(f"Image directory: {image_dir}")
        self.stdout.write(f"Remove missing: {remove_missing}")
        self.stdout.write(f"Update downloaded_location: {update_location}")
        self.stdout.write("=" * 70)
        self.stdout.write("")

        # Step 1: Get all rows from table
        self.stdout.write("Step 1: Querying table for all rows...")
        all_rows = self._get_all_rows(table_name)
        total_images = len(set(row["image_id"] for row in all_rows))
        self.stdout.write(f"  Found {total_images:,} images ({len(all_rows):,} bboxes) in table")
        self.stdout.write("")

        # Step 2: Check which rows have missing/existing files
        self.stdout.write("Step 2: Checking file existence...")
        missing_rows, needs_update_rows, already_correct_rows = self._check_files(all_rows, image_dir)
        missing_images = len(set(row["image_id"] for row in missing_rows))
        needs_update_images = len(set(row["image_id"] for row in needs_update_rows))
        already_correct_images = len(set(row["image_id"] for row in already_correct_rows))
        total_existing = len(needs_update_rows) + len(already_correct_rows)
        total_existing_images = len(set(row["image_id"] for row in needs_update_rows + already_correct_rows))
        self.stdout.write(f"  Found {total_existing_images:,} images ({total_existing:,} bboxes) with files")
        self.stdout.write(f"    - {already_correct_images:,} images ({len(already_correct_rows):,} bboxes) already have correct downloaded_location")
        self.stdout.write(f"    - {needs_update_images:,} images ({len(needs_update_rows):,} bboxes) need downloaded_location update")
        self.stdout.write(f"  Found {missing_images:,} images ({len(missing_rows):,} bboxes) with missing files")
        self.stdout.write("")

        # Step 3: Show summary
        if missing_rows:
            self.stdout.write("Step 3: Summary of rows with missing files")
            self._show_summary(missing_rows)
            self.stdout.write("")

        # Handle --update-downloaded-location
        if update_location and needs_update_rows:
            self._handle_update_location(table_name, needs_update_rows)
        elif update_location and not needs_update_rows:
            self.stdout.write(self.style.SUCCESS("All rows already have correct downloaded_location. Nothing to update."))

        # Handle --remove-missing
        if remove_missing and missing_rows:
            self._handle_remove_missing(table_name, all_rows, missing_rows)
        elif not remove_missing and missing_rows:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {missing_images:,} images with missing files. "
                    "Use --remove-missing to delete these rows."
                )
            )

        if not remove_missing and not update_location:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Verification complete. No changes made."))
            self.stdout.write("Use --remove-missing to delete rows with missing files.")
            self.stdout.write("Use --update-downloaded-location to update file paths.")

    def _handle_update_location(self, table_name, rows_to_update):
        """Handle the update downloaded_location operation"""
        self.stdout.write("=" * 70)
        self.stdout.write("Updating downloaded_location column...")
        self.stdout.write("=" * 70)

        images_to_update = len(set(row["image_id"] for row in rows_to_update))
        self.stdout.write(
            f"Will update {images_to_update:,} images ({len(rows_to_update):,} bboxes) that need new file paths"
        )

        response = input("Proceed with update? (yes/no): ")
        if response.lower() != "yes":
            self.stdout.write(self.style.WARNING("Skipped updating downloaded_location."))
            return

        updated_count = self._update_downloaded_location(table_name, rows_to_update)
        self.stdout.write(self.style.SUCCESS(f"  Updated {updated_count:,} rows with downloaded_location"))
        self.stdout.write("")

    def _handle_remove_missing(self, table_name, all_rows, missing_rows):
        """Handle the remove missing rows operation"""
        missing_images = len(set(row["image_id"] for row in missing_rows))

        self.stdout.write(self.style.WARNING("=" * 70))
        self.stdout.write(
            self.style.WARNING(
                f"This will DELETE {missing_images:,} images ({len(missing_rows):,} bboxes) from {table_name}"
            )
        )
        self.stdout.write(self.style.WARNING("=" * 70))
        response = input("Are you sure you want to proceed? (yes/no): ")

        if response.lower() != "yes":
            self.stdout.write(self.style.ERROR("Aborted. No rows were deleted."))
            return

        self.stdout.write("")
        self.stdout.write("Deleting rows...")
        deleted_count = self._delete_rows(table_name, missing_rows)
        self.stdout.write(self.style.SUCCESS(f"  Deleted {deleted_count:,} rows"))
        self.stdout.write("")

        # Final verification
        remaining_rows = self._get_row_count(table_name)
        remaining_images = self._get_image_count(table_name)
        original_images = len(set(row["image_id"] for row in all_rows))
        deleted_images = len(set(row["image_id"] for row in missing_rows))

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Cleanup Complete!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Original: {original_images:,} images ({len(all_rows):,} bboxes)")
        self.stdout.write(f"Deleted: {deleted_images:,} images ({deleted_count:,} bboxes)")
        self.stdout.write(f"Remaining: {remaining_images:,} images ({remaining_rows:,} bboxes)")
        self.stdout.write("=" * 70)

    def _get_all_rows(self, table_name):
        """Get all rows from table with necessary info"""
        query = f"""
        SELECT
            id,
            image_id,
            dropbox_content_hash,
            species_name,
            camera_station_id,
            to_char(trigger_timestamp, 'YYYY-MM') AS trigger_month,
            downloaded_location
        FROM {table_name}
        ORDER BY id
        """

        rows = []
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                rows.append(dict(zip(columns, row)))

        return rows

    def _check_files(self, rows, image_dir):
        """Check file existence and return (missing_rows, needs_update_rows, already_correct_rows)"""
        missing = []
        needs_update = []
        already_correct = []

        for row in rows:
            content_hash = row["dropbox_content_hash"]
            if not content_hash:
                missing.append(row)
                continue

            # Build path with folder structure: camera_station_id/YYYY-MM/hash.jpg
            camera_station = str(row["camera_station_id"]) if row.get("camera_station_id") else "unknown"
            trigger_month = row.get("trigger_month") or "unknown"
            expected_file = image_dir / camera_station / trigger_month / f"{content_hash}.jpg"

            if expected_file.exists():
                file_path = str(expected_file)
                row["file_path"] = file_path

                # Check if downloaded_location already has the correct value
                # Use case-insensitive comparison for macOS filesystem compatibility
                current_location = row.get("downloaded_location")
                if current_location and current_location.lower() == file_path.lower():
                    already_correct.append(row)
                else:
                    needs_update.append(row)
            else:
                missing.append(row)

        return missing, needs_update, already_correct

    def _show_summary(self, missing_rows):
        """Show summary of missing rows grouped by species (shows both image and bbox counts)"""
        # Group by species
        species_counts = {}
        for row in missing_rows:
            species = row["species_name"]
            if species not in species_counts:
                species_counts[species] = {
                    "bbox_count": 0,
                    "image_ids": set(),
                    "row_ids": [],
                }
            species_counts[species]["bbox_count"] += 1
            species_counts[species]["image_ids"].add(row["image_id"])
            species_counts[species]["row_ids"].append(row["id"])

        # Calculate totals
        total_images = len(set(row["image_id"] for row in missing_rows))
        total_bboxes = len(missing_rows)

        # Sort by bbox count descending
        sorted_species = sorted(
            species_counts.items(), key=lambda x: x[1]["bbox_count"], reverse=True
        )

        self.stdout.write("  Images and bounding boxes with missing files by species:")
        self.stdout.write("  " + "-" * 66)
        for species, data in sorted_species:
            num_images = len(data["image_ids"])
            num_bboxes = data["bbox_count"]
            self.stdout.write(f"  {species:40s} {num_images:4d} images ({num_bboxes:4d} bboxes)")

        self.stdout.write("  " + "-" * 66)
        self.stdout.write(f"  {'TOTAL':40s} {total_images:4d} images ({total_bboxes:4d} bboxes)")
        self.stdout.write("")

        # Show first 10 examples with bbox count per image
        self.stdout.write("  Example images (first 10):")
        seen_images = set()
        examples_shown = 0
        for row in missing_rows:
            if row["image_id"] in seen_images:
                continue
            seen_images.add(row["image_id"])

            # Count bboxes for this image
            bbox_count = sum(1 for r in missing_rows if r["image_id"] == row["image_id"])

            examples_shown += 1
            self.stdout.write(
                f"    {examples_shown:2d}. {row['species_name']:40s} image_id: {row['image_id']} ({bbox_count} bboxes)"
            )

            if examples_shown >= 10:
                break

        if total_images > 10:
            self.stdout.write(f"    ... and {total_images - 10} more images")

    def _update_downloaded_location(self, table_name, rows_with_paths):
        """Update downloaded_location column for rows with existing files"""
        if not rows_with_paths:
            return 0

        # Update in batches
        batch_size = 500
        total_updated = 0

        for i in range(0, len(rows_with_paths), batch_size):
            batch = rows_with_paths[i : i + batch_size]

            # Build CASE statement for batch update
            case_statements = []
            ids = []
            for row in batch:
                case_statements.append(f"WHEN {row['id']} THEN '{row['file_path']}'")
                ids.append(str(row["id"]))

            ids_str = ",".join(ids)
            case_sql = " ".join(case_statements)

            update_sql = f"""
            UPDATE {table_name}
            SET downloaded_location = CASE id {case_sql} END
            WHERE id IN ({ids_str})
            """

            with connection.cursor() as cursor:
                cursor.execute(update_sql)
                total_updated += cursor.rowcount

        return total_updated

    def _delete_rows(self, table_name, rows_to_delete):
        """Delete rows from table"""
        if not rows_to_delete:
            return 0

        # Get list of row IDs to delete
        row_ids = [row["id"] for row in rows_to_delete]

        # Delete in batches of 1000 to avoid too large IN clause
        batch_size = 1000
        total_deleted = 0

        for i in range(0, len(row_ids), batch_size):
            batch = row_ids[i : i + batch_size]
            ids_str = ",".join(str(id) for id in batch)

            delete_sql = f"""
            DELETE FROM {table_name}
            WHERE id IN ({ids_str})
            """

            with connection.cursor() as cursor:
                cursor.execute(delete_sql)
                total_deleted += cursor.rowcount

        return total_deleted

    def _get_row_count(self, table_name):
        """Get total row count from table"""
        query = f"SELECT COUNT(*) FROM {table_name}"

        with connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchone()[0]

    def _get_image_count(self, table_name):
        """Get total unique image count from table"""
        query = f"SELECT COUNT(DISTINCT image_id) FROM {table_name}"

        with connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchone()[0]
