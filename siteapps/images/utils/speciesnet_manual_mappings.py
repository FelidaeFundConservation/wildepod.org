"""
Manual mappings for WildePod SpeciesName scientific names to SpeciesNet UUIDs.

This file handles cases where:
1. WildePod uses different scientific nomenclature than SpeciesNet
2. There are typos or formatting differences
3. Subspecies notation differs
4. Legacy scientific names are used

Each entry maps: WildePod scientific_name -> SpeciesNet UUID
"""
import uuid

# Manual mappings: WildePod scientific_name -> SpeciesNet UUID
MANUAL_SPECIES_MAPPINGS = {
    # Typos/formatting differences
    "Didelphis viginiana": uuid.UUID("87be3a5c-e60a-4e7e-88c7-21544914d067"),  # Virginia opossum (missing 'r')
    "Sylvilagus bachmani:": uuid.UUID("4c5ad642-4465-4b49-97ca-7d6d89223b28"),  # Brush rabbit (extra colon)

    # Different nomenclature (subspecies vs species)
    "Canis lupus familiaris": uuid.UUID("3d80f1d6-b1df-4966-9ff4-94053c7a902a"),  # Domestic dog

    # Old/alternative scientific names
    "Felis domesticus": uuid.UUID("9212982e-8a58-4775-a6ac-e9a43110d8f5"),  # Domestic cat (old name for Felis catus)

    # Subspecies to species mappings (WildePod has subspecies, SpeciesNet has species)
    "Colaptes auratus auratus": uuid.UUID("02799ea2-fba0-4883-b27e-b41ae387e884"),  # Northern Flicker
    "Cervus canadensis nannodes": uuid.UUID("c5ce946f-8f0d-4379-992b-cc0982381f5e"),  # Tule Elk (maps to Elk species)

    # Abbreviated scientific names
    "S. mexicana": uuid.UUID("f1f60795-caf2-4566-b1fd-45c6d66fb37b"),  # Western Bluebird (abbreviated from Sialia mexicana)

    # Different genus names (taxonomic reclassification)
    "Megascops kennicottii": uuid.UUID("69288f26-c835-4ec5-a3e3-29d70df638a1"),  # Western Screech Owl (Megascops -> Otus)

    # Genus-level to species mappings (user-identified specific species)
    "Sylvilagus spp": uuid.UUID("85f0d28f-ca8b-4100-8b16-46d4766201e3"),  # Desert Cottontail (Cottontail rabbit)

    # Add more manual mappings here as needed
    # "Your scientific name": uuid.UUID("speciesnet-uuid-here"),
}

# Genus-level entries (if SpeciesNet has genus-level UUIDs)
# These are intentionally left unmapped for now - add UUIDs if needed
GENUS_LEVEL_ENTRIES = {
    "Anas spp",  # Duck species (genus level)
    "Sciurus spp",  # Unknown squirrel (genus level)
    "Muridae spp",  # Unknown mouse/rat (family level)
    "Unknown Rabbit spp",  # Unknown rabbit (genus level)
    "Bird spp",  # Unknown bird species (class level)
    "Unknown owl species",  # Unknown owl (family level)
}

# Non-animal entries that won't be in SpeciesNet taxonomy
NON_ANIMAL_ENTRIES = {
    "person riding a bike",  # Cyclist
    "person riding a horse (horse+person)",  # Horse rider
    "car, ATV",  # Motorized vehicle
    "bicycle, cyclist",  # Non motorized vehicle
    "N/A",  # Electric Bicycle
    "invertebrate",
    "reptile (any species)",
    "Unknown spp",
    "Consider flagging for staff 1st",
}


def get_manual_mapping(scientific_name: str) -> uuid.UUID:
    """
    Get manual UUID mapping for a scientific name.

    Args:
        scientific_name: Scientific name from WildePod SpeciesName table

    Returns:
        UUID from SpeciesNet taxonomy, or None if no manual mapping exists
    """
    # Normalize the scientific name (lowercase, strip whitespace)
    normalized = scientific_name.lower().strip()

    # Check manual mappings
    for wildepod_name, speciesnet_uuid in MANUAL_SPECIES_MAPPINGS.items():
        if wildepod_name.lower().strip() == normalized:
            return speciesnet_uuid

    return None


def is_genus_level(scientific_name: str) -> bool:
    """Check if this is a genus-level entry that won't match species-level taxonomy."""
    return scientific_name in GENUS_LEVEL_ENTRIES


def is_non_animal(scientific_name: str) -> bool:
    """Check if this is a non-animal entry."""
    return scientific_name in NON_ANIMAL_ENTRIES
