"""
SpeciesNet taxonomy utilities for mapping UUIDs to species information.

Taxonomy format: UUID;class;order;family;genus;species;common_name
Example: febff896-db40-4ac8-bcfe-5bb99a600950;mammalia;artiodactyla;cervidae;odocoileus;hemionus;mule deer
"""
import logging
import uuid
from typing import Dict, Optional, Tuple

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SPECIESNET_TAXONOMY_URL = (
    "https://raw.githubusercontent.com/google/cameratrapai/main/"
    "data/model_package/taxonomy_release.txt"
)
CACHE_KEY = "speciesnet_taxonomy_map"
CACHE_TIMEOUT = 60 * 60 * 24  # 24 hours


class TaxonomyEntry:
    """Parsed SpeciesNet taxonomy entry."""

    def __init__(
        self,
        uuid_str: str,
        class_name: str,
        order: str,
        family: str,
        genus: str,
        species: str,
        common_name: str,
    ):
        self.uuid = uuid.UUID(uuid_str)
        self.class_name = class_name
        self.order = order
        self.family = family
        self.genus = genus
        self.species = species
        self.common_name = common_name.strip().title()  # Normalize casing

    @property
    def scientific_name(self) -> str:
        """Returns genus + species (e.g., 'Odocoileus hemionus')."""
        if self.genus and self.species:
            return f"{self.genus.capitalize()} {self.species}"
        return ""

    def __repr__(self):
        return f"<TaxonomyEntry {self.uuid}: {self.scientific_name} ({self.common_name})>"


def fetch_taxonomy_file() -> str:
    """
    Fetch SpeciesNet taxonomy file from GitHub.

    Returns:
        Raw taxonomy file content as string

    Raises:
        requests.RequestException: If download fails
    """
    logger.info(f"Fetching SpeciesNet taxonomy from {SPECIESNET_TAXONOMY_URL}")
    response = requests.get(SPECIESNET_TAXONOMY_URL, timeout=30)
    response.raise_for_status()
    logger.info(f"Successfully fetched taxonomy file ({len(response.text)} bytes)")
    return response.text


def parse_taxonomy_line(line: str) -> Optional[TaxonomyEntry]:
    """
    Parse a single line from SpeciesNet taxonomy file.

    Args:
        line: Semicolon-separated taxonomy string

    Returns:
        TaxonomyEntry or None if parsing fails
    """
    try:
        parts = line.strip().split(";")
        if len(parts) != 7:
            logger.warning(f"Invalid taxonomy line (expected 7 parts, got {len(parts)}): {line[:100]}")
            return None

        return TaxonomyEntry(*parts)
    except (ValueError, IndexError) as e:
        logger.error(f"Failed to parse taxonomy line: {line[:100]} - {e}")
        return None


def build_taxonomy_map() -> Dict[uuid.UUID, TaxonomyEntry]:
    """
    Build in-memory mapping of SpeciesNet UUID -> TaxonomyEntry.

    Returns:
        Dictionary mapping UUIDs to parsed taxonomy entries
    """
    taxonomy_text = fetch_taxonomy_file()
    taxonomy_map = {}

    for line_num, line in enumerate(taxonomy_text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):  # Skip empty/comment lines
            continue

        entry = parse_taxonomy_line(line)
        if entry:
            taxonomy_map[entry.uuid] = entry
        else:
            logger.warning(f"Skipping invalid line {line_num}")

    logger.info(f"Built taxonomy map with {len(taxonomy_map)} entries")
    return taxonomy_map


def get_taxonomy_map(use_cache: bool = True) -> Dict[uuid.UUID, TaxonomyEntry]:
    """
    Get SpeciesNet taxonomy map with optional caching.

    Args:
        use_cache: Whether to use Django cache (default: True)

    Returns:
        Dictionary mapping UUIDs to taxonomy entries
    """
    if use_cache:
        cached = cache.get(CACHE_KEY)
        if cached:
            logger.debug(f"Using cached taxonomy map ({len(cached)} entries)")
            return cached

    taxonomy_map = build_taxonomy_map()

    if use_cache:
        cache.set(CACHE_KEY, taxonomy_map, CACHE_TIMEOUT)
        logger.info(f"Cached taxonomy map for {CACHE_TIMEOUT}s")

    return taxonomy_map


def extract_taxonomy_from_string(taxonomy_string: str) -> Tuple[Optional[uuid.UUID], str]:
    """
    Extract UUID and common name from SpeciesNet taxonomy string.

    Args:
        taxonomy_string: Full taxonomy string from SpeciesNet API

    Returns:
        Tuple of (UUID, common_name) or (None, common_name) if UUID invalid

    Example:
        >>> extract_taxonomy_from_string("febff896-...-5bb99a600950;mammalia;...;mule deer")
        (UUID('febff896-...'), "Mule Deer")
    """
    if not taxonomy_string:
        return None, "unknown"

    parts = taxonomy_string.split(";")
    if len(parts) < 7:
        return None, parts[-1].strip().title() if parts else "unknown"

    try:
        uuid_obj = uuid.UUID(parts[0])
        common_name = parts[-1].strip().title()
        return uuid_obj, common_name
    except (ValueError, IndexError):
        common_name = parts[-1].strip().title() if len(parts) > 0 else "unknown"
        return None, common_name
