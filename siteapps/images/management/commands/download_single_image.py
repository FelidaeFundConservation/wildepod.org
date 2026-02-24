"""
Download a single image from Dropbox by image_id.

Usage:
    uv run python manage.py download_single_image 270c8892-a99a-408f-80ec-2ca8724908f2 --settings=config.settings.prod
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from siteapps.images.utils.dropbox_client import create_dropbox_client


class Command(BaseCommand):
    help = "Download a single image from Dropbox by image_id"

    def add_arguments(self, parser):
        parser.add_argument(
            "image_id",
            type=str,
            help="The image UUID to download",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Output filename (default: {content_hash}.jpg)",
        )

    def handle(self, *args, **options):
        image_id = options["image_id"]
        output = options["output"]

        self.stdout.write(f"Looking up image: {image_id}")

        # Query database for image info
        row = None
        with connection.cursor() as cursor:
            # Try lila_export tables
            for table in ['lila_export_5', 'lila_export_4', 'lila_export_3', 'lila_export']:
                try:
                    cursor.execute(f'''
                        SELECT dropbox_file_path, dropbox_content_hash, species_name,
                               camera_station_id, to_char(trigger_timestamp, 'YYYY-MM') AS trigger_month
                        FROM {table}
                        WHERE image_id = %s
                        LIMIT 1
                    ''', [image_id])
                    row = cursor.fetchone()
                    if row:
                        self.stdout.write(f"Found in {table}")
                        break
                except Exception:
                    continue

            if not row:
                # Try images_image table directly
                cursor.execute('''
                    SELECT dropbox_file_path, dropbox_content_hash
                    FROM images_image
                    WHERE id = %s
                ''', [image_id])
                row = cursor.fetchone()
                if row:
                    row = (row[0], row[1], 'unknown', None, None)
                    self.stdout.write("Found in images_image")

        if not row:
            raise CommandError(f"Image not found: {image_id}")

        dropbox_path, content_hash, species, camera_station_id, trigger_month = row
        self.stdout.write(f"  Path: {dropbox_path}")
        self.stdout.write(f"  Hash: {content_hash}")
        self.stdout.write(f"  Species: {species}")
        self.stdout.write(f"  Camera Station: {camera_station_id}")
        self.stdout.write(f"  Month: {trigger_month}")

        # Initialize Dropbox client
        dbx = create_dropbox_client()
        if not dbx:
            raise CommandError("Dropbox credentials not configured")

        # Build output path with folder structure: camera_station_id/YYYY-MM/hash.jpg
        if output:
            output_file = Path(output)
        else:
            camera_station = str(camera_station_id) if camera_station_id else "unknown"
            month = trigger_month or "unknown"
            output_dir = Path(camera_station) / month
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{content_hash}.jpg"
        self.stdout.write(f"\nDownloading to: {output_file}")

        try:
            if not dropbox_path.startswith('/'):
                dropbox_path = '/' + dropbox_path

            metadata, response = dbx.files_download(dropbox_path)
            with open(output_file, 'wb') as f:
                f.write(response.content)
            self.stdout.write(self.style.SUCCESS(f"✓ Downloaded successfully: {output_file}"))

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Direct download failed: {e}"))
            self.stdout.write("Trying dropbox_file_index lookup...")

            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT path_display FROM dropbox_file_index WHERE content_hash = %s LIMIT 1",
                        [content_hash]
                    )
                    idx_row = cursor.fetchone()

                if idx_row:
                    new_path = idx_row[0]
                    self.stdout.write(f"  Found relocated path: {new_path}")
                    metadata, response = dbx.files_download(new_path)
                    with open(output_file, 'wb') as f:
                        f.write(response.content)
                    self.stdout.write(self.style.SUCCESS(f"✓ Downloaded successfully: {output_file}"))
                else:
                    raise CommandError("Not found in dropbox_file_index either")

            except CommandError:
                raise
            except Exception as e2:
                raise CommandError(f"Fallback download also failed: {e2}")
