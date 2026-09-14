"""
Management command to ingest MegaDetector and SpeciesNet output JSON files into the database.

## Overview of the Annotation Database Schema

### Core Models

**BoundingBox** (`images_boundingbox`):
- Stores normalized (0–1) bounding box coordinates: `x`, `y`, `w`, `h`
- Linked to an `Image` via FK
- Has a `created_by` FK to an `Annotator` (bot or human)
- `confidence`: detection confidence score from the model
- `confidence_threshold`: the minimum threshold the bot was configured with
- `validity`: UNCERTAIN | VALID | INVALID
- Supports accept/reject voting via ManyToMany to `Annotator`

**Category** (`images_category`):
- Linked to a `BoundingBox` via FK
- `name`: one of 'animal', 'person', 'vehicle', 'unannotated'
- `created_by` FK to `Annotator`
- `confidence`: category confidence from the model

**Species** (`images_species`):
- Linked to a `BoundingBox` via FK
- `name` FK to `SpeciesName` (common name + scientific name)
- `created_by` FK to `Annotator`
- `confidence`: species classification confidence

**Annotator** (`images_annotator`):
- Abstracts both human users and ML bots
- `type`: 'human' or 'bot'
- `bot` FK to `Bot` (for ML models)
- `human` FK to User (for humans)

**Bot** (`images_bot`):
- Stores ML model metadata: `name`, `version`, `task_type`, `threshold`
- Examples: MegaDetector v5a.0.0, SpeciesNet v1.0.0

## How MegaDetector Annotations Are Stored

MegaDetector performs object detection and outputs three category classes:
- "1" → "animal", "2" → "person", "3" → "vehicle"

Each detection creates:
1. A `BoundingBox` with normalized [x, y, w, h] from the JSON bbox, linked to the
   `Annotator` wrapping a MegaDetector `Bot`
2. A `Category` object linked to that `BoundingBox` with name='animal'|'person'|'vehicle'

## How SpeciesNet Annotations Are Stored

SpeciesNet performs both detection and species classification. Each prediction creates:
1. A `BoundingBox` (same structure as MegaDetector)
2. A `Category` object (inferred from the detection category)
3. A `Species` object linked to the `BoundingBox` with a `SpeciesName` FK — the
   SpeciesNet scientific name (e.g. "Puma concolor") is matched against
   `SpeciesName.scientific_name` (case-insensitive). The top-ranked classification
   above the confidence threshold is used.

## Supported JSON Formats

### MegaDetector output (md_v5a.0.0 / md_v5b.0.0)
```json
{
  "images": [
    {
      "file": "relative/path/to/image.jpg",
      "detections": [
        {"category": "1", "conf": 0.926, "bbox": [0.1, 0.2, 0.3, 0.4]}
      ],
      "max_detection_conf": 0.926
    }
  ],
  "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"},
  "info": {"detector": "md_v5a.0.0", "detection_completion_time": "..."}
}
```

### SpeciesNet output (google/speciesnet)
```json
{
  "predictions": {
    "path/to/image.jpg": {
      "detections": [
        {"label": "1", "conf": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4]}
      ],
      "prediction": "mammalia;carnivora;felidae;puma;puma concolor",
      "score": 0.85,
      "predictions_by_classifier": [
        ["mammalia;carnivora;felidae;puma;puma concolor", 0.85],
        ["blank", 0.05]
      ]
    }
  },
  "info": {"model": "speciesnet_v4.0.0a"}
}
```
"""

import json
import logging
import os

from colorama import Fore, Style
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from images.models import Annotator, Bot, BoundingBox, Category, Image, Species, SpeciesName

logger = logging.getLogger(__name__)

# MegaDetector category ID → DB category name mapping
MEGADETECTOR_CATEGORY_MAP = {
    "1": "animal",
    "2": "person",
    "3": "vehicle",
}

# SpeciesNet label ID → DB category name mapping (same IDs as MegaDetector)
SPECIESNET_LABEL_MAP = {
    "1": "animal",
    "2": "person",
    "3": "vehicle",
}

# Non-animal predictions that should be skipped for Species creation
SPECIESNET_NON_SPECIES_PREDICTIONS = {"blank", "unknown", "no_cv_result", ""}

# Default bot configurations
DEFAULT_MEGADETECTOR_NAME = "MegaDetector"
DEFAULT_MEGADETECTOR_VERSION = "v5a.0.0"
DEFAULT_SPECIESNET_NAME = "SpeciesNet"
DEFAULT_SPECIESNET_VERSION = "v1.0.0"


def _extract_scientific_name_from_prediction(prediction: str) -> str:
    """
    Extract the scientific name from a SpeciesNet prediction string.

    SpeciesNet outputs taxonomic paths like:
      "mammalia;carnivora;felidae;puma;puma concolor"

    The last segment is the species binomial name. We capitalize it to match
    the SpeciesName.scientific_name format (e.g. "Puma concolor").
    """
    if not prediction or prediction.strip().lower() in SPECIESNET_NON_SPECIES_PREDICTIONS:
        return ""
    parts = prediction.strip().split(";")
    species_part = parts[-1].strip()
    if not species_part or species_part.lower() in SPECIESNET_NON_SPECIES_PREDICTIONS:
        return ""
    # Capitalize only the genus (first word); species epithet stays lowercase
    words = species_part.split()
    return " ".join([words[0].capitalize()] + words[1:]) if words else ""


def _find_image_by_filepath(filepath: str):
    """
    Find an Image in the database that matches the given filepath from the JSON.

    Matching strategy (in order):
    1. Exact match on dropbox_file_path_display
    2. Case-insensitive match on dropbox_file_path (lowercase path)
    3. Filename-only match (case-insensitive) on dropbox_file_name

    Returns the Image object or None if not found.
    """
    filename = os.path.basename(filepath)
    path_lower = filepath.lower()

    # Try exact path display match first
    image = Image.objects.filter(dropbox_file_path_display=filepath).first()
    if image:
        return image

    # Try lowercase path match
    image = Image.objects.filter(dropbox_file_path=path_lower).first()
    if image:
        return image

    # Fall back to filename-only match (case-insensitive)
    image = Image.objects.filter(dropbox_file_name__iexact=filename).first()
    return image


def _get_or_create_bot_and_annotator(bot_name: str, bot_version: str, task_type: str, threshold: float):
    """Get or create a Bot and its associated Annotator."""
    bot, bot_created = Bot.objects.get_or_create(
        name=bot_name,
        version=bot_version,
        defaults={"task_type": task_type, "threshold": threshold},
    )
    annotator, ann_created = Annotator.objects.get_or_create(type="bot", bot=bot)
    return bot, annotator, bot_created, ann_created


def ingest_megadetector(
    data: dict,
    confidence_threshold: float,
    make_changes: bool,
    stdout=None,
    bot_name_override: str = None,
    bot_version_override: str = None,
) -> dict:
    """
    Ingest a MegaDetector output JSON dictionary into the database.

    For each image entry with detections above the confidence threshold:
    - Finds the corresponding Image record by filepath/filename
    - Creates a BoundingBox with the detection coordinates and confidence
    - Creates a Category object ('animal', 'person', or 'vehicle')

    Returns a summary dict with counts of processed/skipped/created records.
    """

    def _print(msg):
        if stdout:
            stdout.write(msg)
        else:
            print(msg)

    images_list = data.get("images", [])
    detection_categories = data.get("detection_categories", MEGADETECTOR_CATEGORY_MAP)
    info = data.get("info", {})

    # Determine bot name/version: explicit override > JSON info > defaults
    if bot_name_override:
        bot_name = bot_name_override
    else:
        bot_name = DEFAULT_MEGADETECTOR_NAME

    if bot_version_override:
        bot_version = bot_version_override
    else:
        detector_name = info.get("detector", DEFAULT_MEGADETECTOR_VERSION)
        # Strip "md_" prefix if present (e.g. "md_v5a.0.0" -> "v5a.0.0")
        bot_version = detector_name.replace("md_", "") if detector_name.startswith("md_") else detector_name

    bot, annotator, _, _ = _get_or_create_bot_and_annotator(
        bot_name=DEFAULT_MEGADETECTOR_NAME,
        bot_version=bot_version,
        task_type="object_detection",
        threshold=confidence_threshold,
    )

    stats = {
        "images_in_json": len(images_list),
        "images_found": 0,
        "images_not_found": 0,
        "detections_above_threshold": 0,
        "bboxes_created": 0,
        "categories_created": 0,
        "skipped_existing": 0,
    }

    for entry in images_list:
        filepath = entry.get("file", "")
        detections = entry.get("detections", [])

        image = _find_image_by_filepath(filepath)
        if image is None:
            stats["images_not_found"] += 1
            logger.debug(f"Image not found in DB: {filepath}")
            continue

        stats["images_found"] += 1

        for detection in detections:
            conf = detection.get("conf", 0.0)
            if conf < confidence_threshold:
                continue

            stats["detections_above_threshold"] += 1

            bbox_list = detection.get("bbox", [])
            if len(bbox_list) != 4:
                logger.warning(f"Unexpected bbox format for {filepath}: {bbox_list}")
                continue

            x, y, w, h = bbox_list
            category_id = str(detection.get("category", ""))
            category_name = detection_categories.get(category_id, MEGADETECTOR_CATEGORY_MAP.get(category_id, ""))

            if not category_name:
                logger.warning(f"Unknown category id '{category_id}' for {filepath}")
                continue

            if not make_changes:
                continue

            with transaction.atomic():
                bbox, bbox_created = BoundingBox.objects.get_or_create(
                    image=image,
                    created_by=annotator,
                    x=round(x, 6),
                    y=round(y, 6),
                    w=round(w, 6),
                    h=round(h, 6),
                    defaults={
                        "confidence": round(conf, 6),
                        "confidence_threshold": confidence_threshold,
                    },
                )
                if bbox_created:
                    stats["bboxes_created"] += 1
                else:
                    stats["skipped_existing"] += 1

                _, cat_created = Category.objects.get_or_create(
                    bounding_box=bbox,
                    name=category_name,
                    created_by=annotator,
                    defaults={"confidence": round(conf, 6)},
                )
                if cat_created:
                    stats["categories_created"] += 1

    return stats


def ingest_speciesnet(
    data: dict,
    confidence_threshold: float,
    make_changes: bool,
    stdout=None,
    bot_name_override: str = None,
    bot_version_override: str = None,
) -> dict:
    """
    Ingest a SpeciesNet output JSON dictionary into the database.

    SpeciesNet provides both object detection (same bbox format as MegaDetector)
    and species classification. For each image entry:
    - Finds the corresponding Image record by filepath/filename
    - Creates a BoundingBox with detection coordinates and confidence
    - Creates a Category object (from the detection label)
    - If there is a species prediction above the threshold and an animal category,
      looks up the SpeciesName by scientific_name and creates a Species record

    Returns a summary dict with counts of processed/skipped/created records.
    """

    def _print(msg):
        if stdout:
            stdout.write(msg)
        else:
            print(msg)

    # SpeciesNet predictions can be a dict or list
    raw_predictions = data.get("predictions", {})
    info = data.get("info", {})

    # Normalize to list of (filepath, prediction_data) pairs
    if isinstance(raw_predictions, dict):
        prediction_items = list(raw_predictions.items())
    elif isinstance(raw_predictions, list):
        prediction_items = [(p.get("filepath", ""), p) for p in raw_predictions]
    else:
        raise CommandError(f"Unexpected 'predictions' format: {type(raw_predictions)}")

    # Determine bot name/version: explicit override > JSON info > defaults
    if bot_name_override:
        bot_name = bot_name_override
    else:
        bot_name = DEFAULT_SPECIESNET_NAME

    if bot_version_override:
        bot_version = bot_version_override
    else:
        model_name = info.get("model", info.get("detector", DEFAULT_SPECIESNET_VERSION))
        bot_version = model_name if model_name else DEFAULT_SPECIESNET_VERSION

    bot, annotator, _, _ = _get_or_create_bot_and_annotator(
        bot_name=bot_name,
        bot_version=bot_version,
        task_type="object_identification",
        threshold=confidence_threshold,
    )

    stats = {
        "images_in_json": len(prediction_items),
        "images_found": 0,
        "images_not_found": 0,
        "detections_above_threshold": 0,
        "bboxes_created": 0,
        "categories_created": 0,
        "species_created": 0,
        "species_not_matched": 0,
        "skipped_existing": 0,
    }

    for filepath, pred_data in prediction_items:
        if not filepath:
            continue

        image = _find_image_by_filepath(filepath)
        if image is None:
            stats["images_not_found"] += 1
            logger.debug(f"Image not found in DB: {filepath}")
            continue

        stats["images_found"] += 1

        detections = pred_data.get("detections", [])

        # Get the top species prediction for this image (shared across all detections)
        top_prediction = pred_data.get("prediction", "")
        top_score = pred_data.get("score", 0.0)

        # If predictions_by_classifier is provided, find the top valid prediction
        predictions_by_classifier = pred_data.get("predictions_by_classifier", [])
        if predictions_by_classifier and not top_prediction:
            # Sort by score descending and pick the first non-blank prediction
            sorted_preds = sorted(predictions_by_classifier, key=lambda x: x[1], reverse=True)
            for pred_name, pred_score in sorted_preds:
                if pred_name.lower() not in SPECIESNET_NON_SPECIES_PREDICTIONS:
                    top_prediction = pred_name
                    top_score = pred_score
                    break

        scientific_name = _extract_scientific_name_from_prediction(top_prediction)

        # Try to look up the species name in the database
        species_name_obj = None
        if scientific_name and top_score >= confidence_threshold:
            species_name_obj = SpeciesName.objects.filter(
                scientific_name__iexact=scientific_name
            ).first()
            if species_name_obj is None:
                logger.debug(f"SpeciesName not found for scientific name '{scientific_name}' ({filepath})")
                stats["species_not_matched"] += 1

        for detection in detections:
            conf = detection.get("conf", 0.0)
            if conf < confidence_threshold:
                continue

            stats["detections_above_threshold"] += 1

            bbox_list = detection.get("bbox", [])
            if len(bbox_list) != 4:
                logger.warning(f"Unexpected bbox format for {filepath}: {bbox_list}")
                continue

            x, y, w, h = bbox_list

            # SpeciesNet uses "label" for category ID (same IDs as MegaDetector)
            label_id = str(detection.get("label", detection.get("category", "")))
            category_name = SPECIESNET_LABEL_MAP.get(label_id, "")
            # Also accept direct category name strings (e.g. "animal")
            if not category_name and label_id in ("animal", "person", "vehicle"):
                category_name = label_id

            if not category_name:
                logger.warning(f"Unknown label/category '{label_id}' for {filepath}")
                continue

            if not make_changes:
                continue

            with transaction.atomic():
                bbox, bbox_created = BoundingBox.objects.get_or_create(
                    image=image,
                    created_by=annotator,
                    x=round(x, 6),
                    y=round(y, 6),
                    w=round(w, 6),
                    h=round(h, 6),
                    defaults={
                        "confidence": round(conf, 6),
                        "confidence_threshold": confidence_threshold,
                    },
                )
                if bbox_created:
                    stats["bboxes_created"] += 1
                else:
                    stats["skipped_existing"] += 1

                _, cat_created = Category.objects.get_or_create(
                    bounding_box=bbox,
                    name=category_name,
                    created_by=annotator,
                    defaults={"confidence": round(conf, 6)},
                )
                if cat_created:
                    stats["categories_created"] += 1

                # Only create Species records for animal detections with a matched species name
                if species_name_obj and category_name == "animal":
                    _, sp_created = Species.objects.get_or_create(
                        bounding_box=bbox,
                        name=species_name_obj,
                        created_by=annotator,
                        defaults={"confidence": round(top_score, 6)},
                    )
                    if sp_created:
                        stats["species_created"] += 1

    return stats


class Command(BaseCommand):
    help = (
        "Ingest MegaDetector or SpeciesNet output JSON files into the database.\n\n"
        "MegaDetector annotations are stored as BoundingBox + Category records.\n"
        "SpeciesNet annotations are stored as BoundingBox + Category + Species records.\n\n"
        "Use --make_changes to persist results; omit for a dry run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="Path to the MegaDetector or SpeciesNet output JSON file.",
        )
        parser.add_argument(
            "--format",
            dest="format",
            type=str,
            choices=["megadetector", "speciesnet"],
            default=None,
            help=(
                "Format of the JSON file. If not provided, auto-detected from JSON structure "
                "('images' key → megadetector, 'predictions' key → speciesnet)."
            ),
        )
        parser.add_argument(
            "--bot_name",
            type=str,
            default=None,
            help="Override the bot name used to attribute annotations (e.g. 'MegaDetector').",
        )
        parser.add_argument(
            "--bot_version",
            type=str,
            default=None,
            help="Override the bot version used to attribute annotations (e.g. 'v5a.0.0').",
        )
        parser.add_argument(
            "--confidence_threshold",
            type=float,
            default=0.1,
            help="Minimum detection confidence required to store an annotation (default: 0.1).",
        )
        parser.add_argument(
            "--make_changes",
            action="store_true",
            help="Persist changes to the database. Without this flag the command runs as a dry run.",
        )

    def handle(self, *args, **options):
        json_file = options["json_file"]
        fmt = options["format"]
        confidence_threshold = options["confidence_threshold"]
        make_changes = options["make_changes"]

        self.stdout.write("\n================================")
        if make_changes:
            self.stdout.write(f"NOTE: {Fore.GREEN}Changes are enabled.{Style.RESET_ALL} Annotations will be saved.")
        else:
            self.stdout.write(Fore.YELLOW + "NOTE: Dry run mode. No changes will be saved." + Style.RESET_ALL)

        # Load JSON
        if not os.path.isfile(json_file):
            raise CommandError(f"JSON file not found: {json_file}")

        with open(json_file, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise CommandError(f"Failed to parse JSON file: {e}")

        # Auto-detect format if not provided
        if fmt is None:
            if "images" in data:
                fmt = "megadetector"
            elif "predictions" in data:
                fmt = "speciesnet"
            else:
                raise CommandError(
                    "Cannot auto-detect format: JSON must contain an 'images' key (MegaDetector) "
                    "or 'predictions' key (SpeciesNet). Use --format to specify manually."
                )
            self.stdout.write(f"Auto-detected format: {Fore.CYAN}{fmt}{Style.RESET_ALL}")

        self.stdout.write(f"Format:               {fmt}")
        self.stdout.write(f"Confidence threshold: {confidence_threshold}")
        self.stdout.write("================================\n")

        if fmt == "megadetector":
            stats = ingest_megadetector(
                data=data,
                confidence_threshold=confidence_threshold,
                make_changes=make_changes,
                stdout=self.stdout,
                bot_name_override=options.get("bot_name"),
                bot_version_override=options.get("bot_version"),
            )
        elif fmt == "speciesnet":
            stats = ingest_speciesnet(
                data=data,
                confidence_threshold=confidence_threshold,
                make_changes=make_changes,
                stdout=self.stdout,
                bot_name_override=options.get("bot_name"),
                bot_version_override=options.get("bot_version"),
            )
        else:
            raise CommandError(f"Unknown format: {fmt}")

        # Print summary
        self.stdout.write("\n================================")
        self.stdout.write(f"{Fore.GREEN}Ingestion complete.{Style.RESET_ALL}")
        for key, value in stats.items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write("================================\n")
