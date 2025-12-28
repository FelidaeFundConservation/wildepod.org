"""
Management command to populate SpeciesNet UUIDs for existing SpeciesName records.

Usage:
    python manage.py populate_speciesnet_uuids --settings=config.settings.local
    python manage.py populate_speciesnet_uuids --dry-run  # Preview without saving
    python manage.py populate_speciesnet_uuids --force  # Re-map existing UUIDs
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from images.models import SpeciesName
from images.utils.speciesnet_taxonomy import get_taxonomy_map
from images.utils.speciesnet_manual_mappings import get_manual_mapping, is_genus_level, is_non_animal

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Populate SpeciesNet UUIDs for SpeciesName records by matching scientific names"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview matches without saving to database",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-map species that already have UUIDs",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        verbosity = options["verbosity"]

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SpeciesNet UUID Population Tool"))
        self.stdout.write("=" * 70 + "\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be saved\n"))

        # Fetch SpeciesNet taxonomy
        self.stdout.write("Fetching SpeciesNet taxonomy from GitHub...")
        taxonomy_map = get_taxonomy_map(use_cache=False)  # Fresh fetch
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(taxonomy_map)} taxonomy entries\n"))

        # Build reverse lookup: scientific_name -> taxonomy_entry
        scientific_name_map = {}
        for entry in taxonomy_map.values():
            # Normalize scientific names for matching
            normalized = self.normalize_scientific_name(entry.scientific_name)
            if normalized:
                if normalized in scientific_name_map:
                    # Handle duplicates (rare but possible)
                    logger.warning(
                        f"Duplicate scientific name in taxonomy: {entry.scientific_name} "
                        f"(UUIDs: {scientific_name_map[normalized].uuid}, {entry.uuid})"
                    )
                else:
                    scientific_name_map[normalized] = entry

        # Get SpeciesName records to process
        if force:
            species_queryset = SpeciesName.objects.all()
            self.stdout.write(f"Processing ALL {species_queryset.count()} SpeciesName records (--force)\n")
        else:
            species_queryset = SpeciesName.objects.filter(speciesnet_uuid__isnull=True)
            self.stdout.write(f"Processing {species_queryset.count()} SpeciesName records without UUIDs\n")

        # Matching statistics
        exact_matches = 0
        manual_matches = 0
        no_matches = 0
        skipped_genus = 0
        skipped_non_animal = 0
        updated = 0

        unmatched_species = []

        with transaction.atomic():
            for species in species_queryset:
                normalized = self.normalize_scientific_name(species.scientific_name)
                matched_uuid = None
                match_type = None

                # Check if this is a known non-animal entry
                if is_non_animal(species.scientific_name):
                    skipped_non_animal += 1
                    if verbosity >= 1:
                        self.stdout.write(
                            f"  ⊘ Skipping non-animal: {species.name} ({species.scientific_name})"
                        )
                    continue

                # Check if this is a genus-level entry
                if is_genus_level(species.scientific_name):
                    skipped_genus += 1
                    if verbosity >= 1:
                        self.stdout.write(
                            f"  ⊘ Skipping genus-level: {species.name} ({species.scientific_name})"
                        )
                    continue

                # Attempt exact match first
                taxonomy_entry = scientific_name_map.get(normalized)

                if taxonomy_entry:
                    matched_uuid = taxonomy_entry.uuid
                    match_type = "exact"
                    exact_matches += 1
                else:
                    # Try manual mapping
                    manual_uuid = get_manual_mapping(species.scientific_name)
                    if manual_uuid:
                        matched_uuid = manual_uuid
                        match_type = "manual"
                        manual_matches += 1

                if matched_uuid:
                    if verbosity >= 1:
                        match_icon = "✓" if match_type == "exact" else "⚙"
                        match_label = self.style.SUCCESS("exact") if match_type == "exact" else self.style.WARNING("manual")
                        self.stdout.write(
                            f"  {match_icon} {species.name} ({species.scientific_name}) -> "
                            f"UUID: {matched_uuid} [{match_label}]"
                        )

                    if not dry_run:
                        species.speciesnet_uuid = matched_uuid
                        species.save(update_fields=["speciesnet_uuid"])
                        updated += 1
                else:
                    no_matches += 1
                    unmatched_species.append(
                        {
                            "name": species.name,
                            "scientific_name": species.scientific_name,
                            "normalized": normalized,
                        }
                    )

                    if verbosity >= 1:
                        self.stdout.write(
                            self.style.WARNING(f"  ✗ No match for: {species.name} ({species.scientific_name})")
                        )

        # Print summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Total processed:    {species_queryset.count()}")
        self.stdout.write(self.style.SUCCESS(f"Exact matches:      {exact_matches}"))
        self.stdout.write(self.style.SUCCESS(f"Manual matches:     {manual_matches}"))
        self.stdout.write(self.style.WARNING(f"Skipped (genus):    {skipped_genus}"))
        self.stdout.write(self.style.WARNING(f"Skipped (non-animal): {skipped_non_animal}"))
        self.stdout.write(self.style.WARNING(f"No matches:         {no_matches}"))

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nRecords updated:    {updated}"))
        else:
            self.stdout.write(self.style.WARNING("\nDRY RUN - No records were updated"))

        # Export unmatched species for manual review
        if unmatched_species and not dry_run:
            self.stdout.write("\n" + "=" * 70)
            self.stdout.write("UNMATCHED SPECIES (for manual review)")
            self.stdout.write("=" * 70)

            for sp in unmatched_species:
                self.stdout.write(
                    f"  - {sp['name']}: {sp['scientific_name']} " f"(normalized: {sp['normalized']})"
                )

            # Optionally write to CSV
            csv_path = "unmapped_species.csv"
            self.stdout.write(f"\nWriting unmatched species to {csv_path}...")
            with open(csv_path, "w") as f:
                f.write("Common Name,Scientific Name,Normalized\n")
                for sp in unmatched_species:
                    f.write(f"{sp['name']},{sp['scientific_name']},{sp['normalized']}\n")
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(unmatched_species)} unmatched species to {csv_path}"))

        self.stdout.write("\n" + "=" * 70 + "\n")

    @staticmethod
    def normalize_scientific_name(name: str) -> str:
        """
        Normalize scientific name for matching.

        - Convert to lowercase
        - Strip whitespace
        - Handle common variations
        """
        normalized = name.lower().strip()
        # Additional normalization rules can be added here
        # e.g., handle subspecies, remove author names, etc.
        return normalized
