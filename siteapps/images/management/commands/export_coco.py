"""
Django management command to export LILA data to COCO Camera Traps JSON format.

Exports metadata from a lila_export table to the COCO Camera Traps format
for use with MegaDetector and other wildlife ML tools.

Usage:
    uv run manage.py export_coco --table lila_export_3_sampleE --output ../lila/lila_export_3_samplee_coco.json  --settings=config.settings.prod

Output format follows: https://github.com/agentmorris/MegaDetector/blob/main/megadetector/data_management/README.md#coco-camera-traps-format
"""
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Export LILA data to COCO Camera Traps JSON format"

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            type=str,
            required=True,
            help="Source table name (e.g., lila_export_3)",
        )
        parser.add_argument(
            "--output",
            type=str,
            required=True,
            help="Output JSON file path (e.g., /data/lila/coco_export.json)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of rows to export (for testing)",
        )

    def handle(self, *args, **options):
        table_name = options["table"]
        output_path = Path(options["output"])

        # Check database backend
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("LILA to COCO Camera Traps Export"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Source table: {table_name}")
        self.stdout.write(f"Output file: {output_path}")
        self.stdout.write("=" * 70)
        self.stdout.write("")

        limit = options["limit"]

        # Step 1: Fetch data
        self.stdout.write("Step 1: Querying database...")
        rows = self._fetch_data(table_name, limit)
        self.stdout.write(f"  Found {len(rows):,} bounding boxes")

        # Step 2: Build COCO format
        self.stdout.write("Step 2: Building COCO format...")
        coco_data = self._build_coco_format(rows)
        self.stdout.write(f"  Categories: {len(coco_data['categories']):,}")
        self.stdout.write(f"  Images: {len(coco_data['images']):,}")
        self.stdout.write(f"  Annotations: {len(coco_data['annotations']):,}")

        # Step 3: Write JSON
        self.stdout.write("Step 3: Writing JSON file...")
        self._write_json(coco_data, output_path)

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Export Complete!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Output: {output_path}")
        self.stdout.write(f"File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
        self.stdout.write("=" * 70)

    def _fetch_data(self, table_name, limit=None):
        """
        Fetch data from lila_export table joined with images_boundingbox.
        Returns list of dicts with image, bbox, and species info.
        """
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = f"""
        SELECT
            le.image_id::text,
            le.bbox_id::text,
            le.dropbox_content_hash,
            le.trigger_timestamp,
            le.camera_station_id,
            le.species_name,
            bb.x, bb.y, bb.w, bb.h
        FROM {table_name} le
        INNER JOIN images_boundingbox bb ON bb.id = le.bbox_id
        WHERE le.dropbox_content_hash IS NOT NULL
        ORDER BY le.image_id, le.bbox_id
        {limit_clause}
        """

        rows = []
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                rows.append(dict(zip(columns, row)))

        return rows

    def _build_coco_format(self, rows):
        """
        Build COCO Camera Traps format from database rows.
        """
        # Build category mapping (species_name -> integer ID)
        species_names = sorted(set(row["species_name"] for row in rows if row["species_name"]))
        category_map = {name: idx + 1 for idx, name in enumerate(species_names)}

        # Build categories list
        categories = [{"id": cat_id, "name": name} for name, cat_id in category_map.items()]

        # Build images list (one per unique image_id)
        images_dict = {}
        for row in rows:
            image_id = row["image_id"]
            if image_id not in images_dict:
                # Build file_name with folder structure: camera_station_id/YYYY-MM/hash.jpg
                trigger_month = row["trigger_timestamp"].strftime("%Y-%m") if row["trigger_timestamp"] else "unknown"
                camera_station = str(row["camera_station_id"]) if row.get("camera_station_id") else "unknown"
                image_entry = {
                    "id": image_id,
                    "file_name": f"{camera_station}/{trigger_month}/{row['dropbox_content_hash']}.jpg",
                }

                # Add datetime if available
                if row["trigger_timestamp"]:
                    image_entry["datetime"] = row["trigger_timestamp"].isoformat()

                # Add location if available
                if row.get("camera_station_id"):
                    image_entry["location"] = str(row["camera_station_id"])

                images_dict[image_id] = image_entry

        images = list(images_dict.values())

        # Build annotations list (one per bbox)
        annotations = []
        for row in rows:
            annotation = {
                "id": row["bbox_id"],
                "image_id": row["image_id"],
                "category_id": category_map.get(row["species_name"], 0),
                "bbox_relative": [
                    float(row["x"]),
                    float(row["y"]),
                    float(row["w"]),
                    float(row["h"]),
                ],
            }
            annotations.append(annotation)

        # Build info section
        info = {
            "version": "1.0",
            "description": "WildePod camera trap dataset exported in COCO Camera Traps format",
            "date_created": datetime.now().isoformat(),
            "contributor": "Felidae Conservation Fund",
        }

        return {
            "info": info,
            "images": images,
            "categories": categories,
            "annotations": annotations,
        }

    def _write_json(self, data, output_path):
        """Write COCO data to JSON file."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
