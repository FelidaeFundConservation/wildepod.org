"""
Django management command to append random images of a specific species to sample table

Adds <count> random IMAGES matching species_name from source_table to sample_table.
When an image is selected, ALL its bounding boxes are included.
Excludes images already in sample_table to avoid duplicates.

Usage:
    uv run manage.py append_images --source lila_export_3 --sample lila_export_3_sampleE --species "Puma" --count 9   --settings=config.settings.prod
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Append random images of a specific species from source table to sample table (includes all bounding boxes)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            required=True,
            help="Source table name (e.g., lila_export_3)",
        )
        parser.add_argument(
            "--sample",
            type=str,
            required=True,
            help="Sample table name (e.g., lila_export_3_sample)",
        )
        parser.add_argument(
            "--species",
            type=str,
            required=True,
            help="Species name to filter (e.g., 'Gray Fox')",
        )
        parser.add_argument(
            "--count",
            type=int,
            required=True,
            help="Number of images to append",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for reproducibility (default: 42)",
        )

    def handle(self, *args, **options):
        source_table = options["source"]
        sample_table = options["sample"]
        species_name = options["species"]
        count = options["count"]
        seed = options["seed"]

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        if count <= 0:
            raise CommandError("Count must be greater than 0")

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Append Images"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {source_table}")
        self.stdout.write(f"Sample table: {sample_table}")
        self.stdout.write(f"Species: {species_name}")
        self.stdout.write(f"Images to append: {count:,}")
        self.stdout.write(f"Random seed: {seed}")
        self.stdout.write("=" * 70)
        self.stdout.write("")

        # Step 1: Check current state
        self.stdout.write("Step 1: Analyzing current state...")
        stats = self._get_current_state(source_table, sample_table, species_name)

        self.stdout.write(f"  Source table total images: {stats['source_total_images']:,}")
        self.stdout.write(f"  Source table total bboxes: {stats['source_total_bboxes']:,}")
        self.stdout.write(f"  Source table '{species_name}' images: {stats['source_species_images']:,}")
        self.stdout.write(f"  Sample table total images: {stats['sample_total_images']:,}")
        self.stdout.write(f"  Sample table total bboxes: {stats['sample_total_bboxes']:,}")
        self.stdout.write(f"  Sample table '{species_name}' images: {stats['sample_species_images']:,}")
        self.stdout.write(f"  Available to add (not in sample): {stats['available_images']:,} images")
        self.stdout.write("")

        # Check if we have enough images
        if stats['available_images'] < count:
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: Only {stats['available_images']:,} images available, but {count:,} requested."
                )
            )
            self.stdout.write(
                self.style.WARNING(f"Will add all {stats['available_images']:,} available images.")
            )
            actual_count = stats['available_images']
        else:
            actual_count = count

        if actual_count == 0:
            self.stdout.write(self.style.ERROR("No images available to add!"))
            return

        # Step 2: Select random images to append
        self.stdout.write(f"Step 2: Selecting {actual_count:,} random images...")
        selected_image_ids, all_bbox_ids = self._select_random_images(
            source_table, sample_table, species_name, actual_count, seed
        )
        self.stdout.write(f"  Selected {len(selected_image_ids):,} images")
        self.stdout.write(f"  Total bounding boxes: {len(all_bbox_ids):,}")
        self.stdout.write("")

        # Step 3: Show sample of what will be added
        self.stdout.write("Step 3: Preview of images to be added (first 5):")
        preview = self._preview_images(source_table, selected_image_ids[:5])
        for i, row in enumerate(preview, 1):
            self.stdout.write(
                f"  {i}. image_id: {row['image_id']} | species: {row['species_name']} | bboxes: {row['bbox_count']}"
            )
        if len(selected_image_ids) > 5:
            self.stdout.write(f"  ... and {len(selected_image_ids) - 5} more images")
        self.stdout.write("")

        # Step 4: Ask for confirmation
        self.stdout.write(self.style.WARNING("=" * 70))
        self.stdout.write(
            self.style.WARNING(
                f"This will ADD {len(selected_image_ids):,} images ({len(all_bbox_ids):,} bboxes) to {sample_table}"
            )
        )
        self.stdout.write(self.style.WARNING("=" * 70))
        response = input("Are you sure you want to proceed? (yes/no): ")

        if response.lower() != "yes":
            self.stdout.write(self.style.ERROR("Aborted. No rows were added."))
            return

        # Step 5: Insert rows
        self.stdout.write("")
        self.stdout.write("Step 5: Inserting rows...")
        inserted_count = self._insert_rows(source_table, sample_table, all_bbox_ids)
        self.stdout.write(self.style.SUCCESS(f"  ✓ Inserted {inserted_count:,} bounding box rows"))
        self.stdout.write("")

        # Step 6: Final verification
        final_stats = self._get_current_state(source_table, sample_table, species_name)
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Append Complete!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Sample table images before: {stats['sample_total_images']:,}")
        self.stdout.write(f"Sample table images after: {final_stats['sample_total_images']:,}")
        self.stdout.write(f"Sample table bboxes before: {stats['sample_total_bboxes']:,}")
        self.stdout.write(f"Sample table bboxes after: {final_stats['sample_total_bboxes']:,}")
        self.stdout.write(f"'{species_name}' images before: {stats['sample_species_images']:,}")
        self.stdout.write(f"'{species_name}' images after: {final_stats['sample_species_images']:,}")
        self.stdout.write(f"Added: {len(selected_image_ids):,} images, {inserted_count:,} bboxes")
        self.stdout.write("=" * 70)

    def _get_current_state(self, source_table, sample_table, species_name):
        """Get current image and bbox counts for source and sample tables"""
        with connection.cursor() as cursor:
            # Source table stats
            cursor.execute(f"SELECT COUNT(DISTINCT image_id) FROM {source_table}")
            source_total_images = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {source_table}")
            source_total_bboxes = cursor.fetchone()[0]

            # Source species images (using primary species logic)
            cursor.execute(
                f"""
                WITH image_species AS (
                    SELECT DISTINCT ON (image_id)
                        image_id,
                        species_name
                    FROM (
                        SELECT
                            image_id,
                            species_name,
                            COUNT(*) as bbox_count
                        FROM {source_table}
                        GROUP BY image_id, species_name
                    ) species_counts
                    ORDER BY image_id, bbox_count DESC, species_name
                )
                SELECT COUNT(DISTINCT image_id)
                FROM image_species
                WHERE species_name = %s
                """,
                [species_name],
            )
            source_species_images = cursor.fetchone()[0]

            # Sample table stats
            cursor.execute(f"SELECT COUNT(DISTINCT image_id) FROM {sample_table}")
            sample_total_images = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {sample_table}")
            sample_total_bboxes = cursor.fetchone()[0]

            cursor.execute(
                f"""
                WITH image_species AS (
                    SELECT DISTINCT ON (image_id)
                        image_id,
                        species_name
                    FROM (
                        SELECT
                            image_id,
                            species_name,
                            COUNT(*) as bbox_count
                        FROM {sample_table}
                        GROUP BY image_id, species_name
                    ) species_counts
                    ORDER BY image_id, bbox_count DESC, species_name
                )
                SELECT COUNT(DISTINCT image_id)
                FROM image_species
                WHERE species_name = %s
                """,
                [species_name],
            )
            sample_species_images = cursor.fetchone()[0]

            # Available to add (images in source but not in sample)
            cursor.execute(
                f"""
                WITH image_species AS (
                    SELECT DISTINCT ON (image_id)
                        image_id,
                        species_name
                    FROM (
                        SELECT
                            image_id,
                            species_name,
                            COUNT(*) as bbox_count
                        FROM {source_table}
                        GROUP BY image_id, species_name
                    ) species_counts
                    ORDER BY image_id, bbox_count DESC, species_name
                )
                SELECT COUNT(DISTINCT image_id)
                FROM image_species
                WHERE species_name = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM {sample_table} smp
                    WHERE smp.image_id = image_species.image_id
                  )
                """,
                [species_name],
            )
            available_images = cursor.fetchone()[0]

        return {
            "source_total_images": source_total_images,
            "source_total_bboxes": source_total_bboxes,
            "source_species_images": source_species_images,
            "sample_total_images": sample_total_images,
            "sample_total_bboxes": sample_total_bboxes,
            "sample_species_images": sample_species_images,
            "available_images": available_images,
        }

    def _select_random_images(self, source_table, sample_table, species_name, count, seed):
        """
        Select random image_ids from source that aren't in sample,
        then get all bounding box row IDs for those images.

        Returns:
            tuple: (selected_image_ids, all_bbox_row_ids)
        """
        # Select image_ids for this species (using primary species logic)
        query = f"""
        WITH image_species AS (
            SELECT DISTINCT ON (image_id)
                image_id,
                species_name
            FROM (
                SELECT
                    image_id,
                    species_name,
                    COUNT(*) as bbox_count
                FROM {source_table}
                GROUP BY image_id, species_name
            ) species_counts
            ORDER BY image_id, bbox_count DESC, species_name
        )
        SELECT image_id
        FROM image_species
        WHERE species_name = %s
          AND NOT EXISTS (
            SELECT 1 FROM {sample_table} smp
            WHERE smp.image_id = image_species.image_id
          )
        ORDER BY RANDOM()
        LIMIT %s
        """

        with connection.cursor() as cursor:
            # Set seed for reproducibility
            cursor.execute(f"SELECT setseed({seed / 1000000.0})")
            cursor.execute(query, [species_name, count])
            image_ids = [row[0] for row in cursor.fetchall()]

        if not image_ids:
            return [], []

        # Now get ALL bounding box row IDs for the selected images
        image_ids_str = ",".join(f"'{str(img_id)}'" for img_id in image_ids)
        bbox_query = f"""
        SELECT id
        FROM {source_table}
        WHERE image_id IN ({image_ids_str})
        ORDER BY image_id, id
        """

        with connection.cursor() as cursor:
            cursor.execute(bbox_query)
            bbox_ids = [row[0] for row in cursor.fetchall()]

        return image_ids, bbox_ids

    def _preview_images(self, source_table, image_ids):
        """Get preview of images to be inserted"""
        if not image_ids:
            return []

        image_ids_str = ",".join(f"'{str(img_id)}'" for img_id in image_ids)
        query = f"""
        WITH image_species AS (
            SELECT DISTINCT ON (image_id)
                image_id,
                species_name
            FROM (
                SELECT
                    image_id,
                    species_name,
                    COUNT(*) as bbox_count
                FROM {source_table}
                WHERE image_id IN ({image_ids_str})
                GROUP BY image_id, species_name
            ) species_counts
            ORDER BY image_id, bbox_count DESC, species_name
        ),
        image_bbox_counts AS (
            SELECT
                image_id,
                COUNT(*) as bbox_count
            FROM {source_table}
            WHERE image_id IN ({image_ids_str})
            GROUP BY image_id
        )
        SELECT
            img_sp.image_id,
            img_sp.species_name,
            img_bc.bbox_count
        FROM image_species img_sp
        INNER JOIN image_bbox_counts img_bc ON img_sp.image_id = img_bc.image_id
        ORDER BY img_sp.image_id
        """

        rows = []
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                rows.append(dict(zip(columns, row)))

        return rows

    def _insert_rows(self, source_table, sample_table, bbox_ids):
        """Insert selected bounding box rows into sample table"""
        if not bbox_ids:
            return 0

        ids_str = ",".join(str(id) for id in bbox_ids)

        insert_sql = f"""
        INSERT INTO {sample_table}
        SELECT * FROM {source_table}
        WHERE id IN ({ids_str})
        """

        with connection.cursor() as cursor:
            cursor.execute(insert_sql)
            return cursor.rowcount
