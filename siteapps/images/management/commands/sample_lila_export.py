"""
Django management command to create a stratified sample from LILA export table

Sampling strategy:
- Species proportions calculated at BOUNDING BOX level (ensures all species are counted)
- When an image is selected, ALL its bounding boxes are included
- Guarantees minimum samples per species (default 5)
- If species has <5 bboxes, includes all images containing it
- Fills remaining slots proportionally based on species bbox frequency
- Total target: 1000 samples (configurable)

Usage:
    uv run manage.py sample_lila_export --source lila_export_3 --dest lila_export_3_sample
    uv run manage.py sample_lila_export --source lila_export_3 --dest lila_export_3_sample --sample-size 2000
"""
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create stratified sample from LILA export table (proportions based on bbox counts, samples images)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            required=True,
            help="Source table name (e.g., lila_export_3)",
        )
        parser.add_argument(
            "--dest",
            type=str,
            required=True,
            help="Destination table name (e.g., lila_export_3_sample)",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=1000,
            help="Target total sample size (default: 1000)",
        )
        parser.add_argument(
            "--min-per-species",
            type=int,
            default=5,
            help="Minimum samples per species if available (default: 5)",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for reproducibility (default: 42)",
        )

    def handle(self, *args, **options):
        source_table = options["source"]
        dest_table = options["dest"]
        target_size = options["sample_size"]
        min_per_species = options["min_per_species"]
        seed = options["seed"]

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("LILA Export Stratified Sampling"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {source_table}")
        self.stdout.write(f"Destination table: {dest_table}")
        self.stdout.write(f"Target sample size: {target_size:,}")
        self.stdout.write(f"Minimum per species: {min_per_species}")
        self.stdout.write(f"Random seed: {seed}")
        self.stdout.write("=" * 70)
        self.stdout.write("")

        # Step 1: Get species counts (at bbox level)
        self.stdout.write("Step 1: Analyzing species distribution (bbox level)...")
        species_counts = self._get_species_counts(source_table)

        total_bboxes = species_counts["count"].sum()
        num_species = len(species_counts)

        self.stdout.write(f"  Total bounding boxes: {total_bboxes:,}")
        self.stdout.write(f"  Unique species: {num_species}")
        self.stdout.write("")

        # Step 2: Calculate sampling plan
        self.stdout.write("Step 2: Calculating sampling plan...")
        sampling_plan = self._calculate_sampling_plan(
            species_counts, target_size, min_per_species
        )

        total_to_sample = sampling_plan["sample_count"].sum()
        self.stdout.write(f"  Total to sample: {total_to_sample:,}")
        self.stdout.write(
            f"  Species with <{min_per_species} bboxes: {len(sampling_plan[sampling_plan['available'] < min_per_species])}"
        )
        self.stdout.write(
            f"  Species getting minimum ({min_per_species}): {len(sampling_plan[sampling_plan['sample_count'] == min_per_species])}"
        )
        self.stdout.write(
            f"  Species getting proportional: {len(sampling_plan[sampling_plan['sample_count'] > min_per_species])}"
        )
        self.stdout.write("")

        # Step 3: Sample the data
        self.stdout.write("Step 3: Sampling images from source table...")
        sampled_image_ids, all_bbox_ids = self._sample_data(source_table, sampling_plan, seed)
        self.stdout.write(f"  Sampled {len(sampled_image_ids):,} images")
        self.stdout.write(f"  Total bounding boxes: {len(all_bbox_ids):,}")
        self.stdout.write("")

        # Step 4: Create destination table
        self.stdout.write(f"Step 4: Creating destination table {dest_table}...")
        self._create_sample_table(source_table, dest_table, all_bbox_ids)
        self.stdout.write(self.style.SUCCESS(f"  ✓ Table {dest_table} created"))
        self.stdout.write("")

        # Step 5: Summary statistics
        self.stdout.write("Step 5: Verifying sample distribution...")
        self._show_summary(dest_table, sampling_plan)

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Sampling Complete!"))
        self.stdout.write("=" * 70)

    def _get_species_counts(self, table_name):
        """
        Get count of bounding boxes per species.

        Works at bbox level to ensure all species are counted correctly,
        including rare species that only appear as secondary annotations.
        """
        query = f"""
        SELECT
            species_name,
            COUNT(*) as count
        FROM {table_name}
        GROUP BY species_name
        ORDER BY count DESC
        """
        return pd.read_sql(query, connection)

    def _calculate_sampling_plan(self, species_counts, target_size, min_per_species):
        """
        Calculate how many samples per species based on bbox proportions.

        Strategy:
        1. Species with <min_per_species bboxes: take all available
        2. Other species: initially allocate min_per_species each
        3. Remaining slots: distribute proportionally by bbox count
        """
        df = species_counts.copy()
        df["available"] = df["count"]
        df["sample_count"] = 0

        # Step 1: Allocate for species with fewer than min samples
        rare_species = df["available"] < min_per_species
        df.loc[rare_species, "sample_count"] = df.loc[rare_species, "available"]

        # Step 2: Allocate minimum for other species
        common_species = df["available"] >= min_per_species
        df.loc[common_species, "sample_count"] = min_per_species

        # Step 3: Calculate remaining slots
        allocated = df["sample_count"].sum()
        remaining = target_size - allocated

        if remaining > 0:
            # Distribute remaining slots proportionally among common species
            common_df = df[common_species].copy()
            common_df["proportion"] = common_df["count"] / common_df["count"].sum()
            common_df["exact_additional"] = common_df["proportion"] * remaining

            # Use floor for initial allocation
            common_df["additional"] = common_df["exact_additional"].astype(int)

            # Calculate shortfall due to floor rounding
            shortfall = remaining - common_df["additional"].sum()

            # Distribute shortfall to species with largest fractional remainders
            if shortfall > 0:
                common_df["fractional"] = common_df["exact_additional"] - common_df["additional"]
                # Get indices of top N species by fractional part
                top_fractional = common_df.nlargest(int(shortfall), "fractional").index
                common_df.loc[top_fractional, "additional"] += 1

            # Ensure we don't exceed available samples
            common_df["additional"] = common_df[["additional", "available"]].apply(
                lambda x: min(x["additional"], x["available"] - min_per_species), axis=1
            )

            # Add additional samples
            df.loc[common_species, "sample_count"] += common_df["additional"].values

            # Final check: if we're still short due to availability constraints, top up
            final_allocated = df["sample_count"].sum()
            final_shortfall = target_size - final_allocated

            if final_shortfall > 0:
                # Find species with room to give more (have available > sample_count)
                can_give_more = df[df["available"] > df["sample_count"]]
                if len(can_give_more) > 0:
                    # Sort by available space (descending)
                    can_give_more = can_give_more.sort_values(
                        by=["available"], ascending=False
                    )
                    # Distribute shortfall
                    for idx in can_give_more.index:
                        if final_shortfall <= 0:
                            break
                        max_can_add = df.loc[idx, "available"] - df.loc[idx, "sample_count"]
                        add_count = min(final_shortfall, max_can_add)
                        df.loc[idx, "sample_count"] += add_count
                        final_shortfall -= add_count

        return df

    def _sample_data(self, table_name, sampling_plan, seed):
        """
        Sample images containing each species according to sampling plan,
        then get all bounding box row IDs for those images.

        Returns:
            tuple: (sampled_image_ids, all_bbox_row_ids)
        """
        sampled_image_ids = set()

        for _, row in sampling_plan.iterrows():
            species_name = row["species_name"]
            sample_count = int(row["sample_count"])

            if sample_count == 0:
                continue

            # Build exclusion clause for already-sampled images
            if sampled_image_ids:
                exclusion_list = ",".join(f"'{str(img_id)}'" for img_id in sampled_image_ids)
                exclusion_clause = f"AND image_id NOT IN ({exclusion_list})"
            else:
                exclusion_clause = ""

            # Sample image_ids that contain this species (excluding already sampled)
            query = f"""
            SELECT image_id
            FROM (
                SELECT DISTINCT image_id
                FROM {table_name}
                WHERE species_name = %s
                {exclusion_clause}
            ) distinct_images
            ORDER BY RANDOM()
            LIMIT %s
            """

            with connection.cursor() as cursor:
                # Set seed for reproducibility
                cursor.execute(f"SELECT setseed({seed / 1000000.0})")
                cursor.execute(query, [species_name, sample_count])
                image_ids = [r[0] for r in cursor.fetchall()]
                sampled_image_ids.update(image_ids)

        # Now get ALL bounding box row IDs for the sampled images
        if not sampled_image_ids:
            return [], []

        image_ids_str = ",".join(f"'{str(img_id)}'" for img_id in sampled_image_ids)
        bbox_query = f"""
        SELECT id
        FROM {table_name}
        WHERE image_id IN ({image_ids_str})
        ORDER BY image_id, id
        """

        with connection.cursor() as cursor:
            cursor.execute(bbox_query)
            bbox_ids = [row[0] for row in cursor.fetchall()]

        return list(sampled_image_ids), bbox_ids

    def _create_sample_table(self, source_table, dest_table, sampled_ids):
        """
        Create destination table with sampled rows

        Args:
            sampled_ids: List of bounding box row IDs (not image_ids)
        """
        # Convert IDs to comma-separated string
        ids_str = ",".join(str(id) for id in sampled_ids)

        create_sql = f"""
        DROP TABLE IF EXISTS {dest_table} CASCADE;

        SELECT *
        INTO {dest_table}
        FROM {source_table}
        WHERE id IN ({ids_str});

        -- Create indexes
        -- CREATE INDEX idx_{dest_table}_image_id ON {dest_table}(image_id);
        -- CREATE INDEX idx_{dest_table}_bbox_id ON {dest_table}(bbox_id);
        -- CREATE INDEX idx_{dest_table}_trigger_timestamp ON {dest_table}(trigger_timestamp);
        -- CREATE INDEX idx_{dest_table}_species ON {dest_table}(species_name);
        """

        with connection.cursor() as cursor:
            cursor.execute(create_sql)

    def _show_summary(self, table_name, original_plan):
        """Show summary of actual vs planned distribution"""
        actual = self._get_species_counts(table_name)

        # Get totals
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            total_bboxes = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(DISTINCT image_id) FROM {table_name}")
            total_images = cursor.fetchone()[0]

        self.stdout.write(f"  Total in sample: {total_images:,} images, {total_bboxes:,} bounding boxes")
        self.stdout.write("")

        # Merge with plan
        comparison = original_plan.merge(
            actual, on="species_name", suffixes=("_available", "_actual")
        )
        comparison = comparison[
            ["species_name", "count_available", "sample_count", "count_actual"]
        ]
        comparison.columns = ["species", "available_bboxes", "planned", "actual_bboxes"]

        # Show top 10 and bottom 10
        self.stdout.write("  Top 10 species by bbox count:")
        for _, row in comparison.nlargest(10, "actual_bboxes").iterrows():
            self.stdout.write(
                f"    {row['species']:40s} {row['actual_bboxes']:4d} / {row['available_bboxes']:6d} bboxes ({row['actual_bboxes']/row['available_bboxes']*100:5.1f}%)"
            )

        self.stdout.write("")
        self.stdout.write("  Bottom 10 species by bbox count:")
        for _, row in comparison.nsmallest(10, "actual_bboxes").iterrows():
            self.stdout.write(
                f"    {row['species']:40s} {row['actual_bboxes']:4d} / {row['available_bboxes']:6d} bboxes ({row['actual_bboxes']/row['available_bboxes']*100:5.1f}%)"
            )
