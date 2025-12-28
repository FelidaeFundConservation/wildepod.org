"""
Service for mapping SpeciesNet taxonomy to WildePod SpeciesName records.
"""
import logging
import uuid as uuid_lib
from typing import Dict, List, Optional, Set

from django.db.models import Q

from images.models import SpeciesName
from .speciesnet_taxonomy import TaxonomyEntry, get_taxonomy_map

logger = logging.getLogger(__name__)


class SpeciesMapper:
    """
    Maps SpeciesNet UUIDs to WildePod SpeciesName records.

    Uses in-memory cache for fast real-time lookups during image processing.
    """

    def __init__(self):
        """Initialize mapper with taxonomy and SpeciesName lookup caches."""
        self._taxonomy_map: Optional[Dict[uuid_lib.UUID, TaxonomyEntry]] = None
        self._uuid_to_species: Optional[Dict[uuid_lib.UUID, SpeciesName]] = None
        self._unmapped_uuids: Set[uuid_lib.UUID] = set()

    def _load_taxonomy(self):
        """Lazy-load SpeciesNet taxonomy map."""
        if self._taxonomy_map is None:
            logger.info("Loading SpeciesNet taxonomy map...")
            self._taxonomy_map = get_taxonomy_map(use_cache=True)
            logger.info(f"Loaded {len(self._taxonomy_map)} taxonomy entries")

    def _build_species_cache(self):
        """Build UUID -> SpeciesName lookup cache from database."""
        if self._uuid_to_species is None:
            logger.info("Building SpeciesName UUID lookup cache...")

            # Query all SpeciesName records with UUIDs
            species_with_uuids = SpeciesName.objects.filter(speciesnet_uuid__isnull=False).select_related()

            self._uuid_to_species = {sp.speciesnet_uuid: sp for sp in species_with_uuids}

            logger.info(f"Built cache with {len(self._uuid_to_species)} mapped species")

    def lookup_species(self, speciesnet_uuid: uuid_lib.UUID) -> Optional[SpeciesName]:
        """
        Lookup SpeciesName by SpeciesNet UUID.

        Args:
            speciesnet_uuid: UUID from SpeciesNet taxonomy

        Returns:
            SpeciesName object if mapped, None otherwise
        """
        # Ensure caches are loaded
        self._load_taxonomy()
        self._build_species_cache()

        # Fast lookup from in-memory cache
        species = self._uuid_to_species.get(speciesnet_uuid)

        if species:
            return species

        # Track unmapped UUIDs for logging
        if speciesnet_uuid not in self._unmapped_uuids:
            self._unmapped_uuids.add(speciesnet_uuid)

            # Get taxonomy info for better logging
            taxonomy = self._taxonomy_map.get(speciesnet_uuid)
            if taxonomy:
                logger.warning(
                    f"Unmapped species detected - UUID: {speciesnet_uuid}, "
                    f"Scientific: {taxonomy.scientific_name}, "
                    f"Common: {taxonomy.common_name}"
                )
            else:
                logger.warning(f"Unknown SpeciesNet UUID: {speciesnet_uuid}")

        return None

    def get_unmapped_species_report(self) -> List[Dict]:
        """
        Generate report of unmapped species for manual review.

        Returns:
            List of dicts with UUID, scientific name, common name
        """
        self._load_taxonomy()

        report = []
        for uuid in sorted(self._unmapped_uuids):
            taxonomy = self._taxonomy_map.get(uuid)
            if taxonomy:
                report.append(
                    {
                        "uuid": str(uuid),
                        "scientific_name": taxonomy.scientific_name,
                        "common_name": taxonomy.common_name,
                        "class": taxonomy.class_name,
                        "family": taxonomy.family,
                    }
                )

        return report

    def refresh_cache(self):
        """Force refresh of internal caches."""
        logger.info("Refreshing SpeciesMapper caches...")
        self._taxonomy_map = None
        self._uuid_to_species = None
        self._unmapped_uuids.clear()
        self._load_taxonomy()
        self._build_species_cache()


# Global singleton instance for reuse across requests
_global_mapper: Optional[SpeciesMapper] = None


def get_species_mapper() -> SpeciesMapper:
    """
    Get global SpeciesMapper instance (singleton pattern).

    Returns:
        Initialized SpeciesMapper instance
    """
    global _global_mapper
    if _global_mapper is None:
        _global_mapper = SpeciesMapper()
    return _global_mapper
