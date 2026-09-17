"""Populate a local development database with realistic sample data.

Local dev starts with an empty database, which leaves the annotation queue,
explore pages and search screens with nothing to render. This command builds a
small but complete slice of the real data model: a location hierarchy, camera
stations, uploads, images with generated placeholder photos, MegaDetector-style
bounding boxes, and a handful of volunteer accounts.

Intended for config.settings.local only. It refuses to run against a non-SQLite
database so it can't be pointed at staging or prod by accident.

    uv run manage.py seed_local_data --settings=config.settings.local
    uv run manage.py seed_local_data --images 60 --flush --settings=config.settings.local
"""

import random
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from images.models import Annotator, Bot, BoundingBox, CameraStationAction, Category, Image, SpeciesName, Upload
from images.models.annotation import ActivityType
from locations.models import Area, CameraStation, County, Grid, MacroSite, MicroSite
from PIL import Image as PILImage
from PIL import ImageDraw
from users.models import User

# Species that actually turn up on Felidae's California camera traps.
SPECIES = [
    ("Mountain Lion", "Puma concolor", "WILD"),
    ("Bobcat", "Lynx rufus", "WILD"),
    ("Coyote", "Canis latrans", "WILD"),
    ("Gray Fox", "Urocyon cinereoargenteus", "WILD"),
    ("Black Bear", "Ursus americanus", "WILD"),
    ("Mule Deer", "Odocoileus hemionus", "WILD"),
    ("Raccoon", "Procyon lotor", "WILD"),
    ("Striped Skunk", "Mephitis mephitis", "WILD"),
    ("Domestic Dog", "Canis familiaris", "DOMESTIC"),
    ("Human", "Homo sapiens", "HUMAN"),
]

ANIMAL_ACTIVITIES = ["Walking", "Running", "Resting", "Foraging", "Scent Marking", "Vocalizing"]
HUMAN_ACTIVITIES = ["Hiking", "Cycling", "Dog Walking", "Hunting", "Vehicle"]

# Muted palette so generated placeholders read as distinct frames, not test noise.
PALETTE = [(94, 108, 84), (120, 106, 82), (78, 92, 96), (110, 96, 104), (86, 100, 72)]


class Command(BaseCommand):
    help = "Seed the local SQLite database with sample WildePod data."

    def add_arguments(self, parser):
        parser.add_argument("--images", type=int, default=40, help="Number of images to create (default 40).")
        parser.add_argument("--stations", type=int, default=3, help="Number of camera stations (default 3).")
        parser.add_argument(
            "--flush",
            action="store_true",
            help=(
                "Before seeding, delete ALL images, uploads, bounding boxes and locations "
                "in the local database -- not just previously seeded ones. Volunteer accounts "
                "are scoped to @wildepod.local and superusers are never touched."
            ),
        )

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError(
                f"Refusing to run: this command is local-only but the database backend is "
                f"'{connection.vendor}'. Run it with --settings=config.settings.local."
            )

        image_count = options["images"]
        station_count = options["stations"]

        if options["flush"]:
            self._flush()

        with transaction.atomic():
            species_names = self._create_species()
            self._create_activity_types()
            volunteers = self._create_volunteers()
            stations = self._create_locations(station_count)
            bot_annotator = self._create_bot_annotator()
            self._create_images(image_count, stations, volunteers, bot_annotator, species_names)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seed complete."))
        for label, count in [
            ("Species names", SpeciesName.objects.count()),
            ("Activity types", ActivityType.objects.count()),
            ("Camera stations", CameraStation.objects.count()),
            ("Uploads", Upload.objects.count()),
            ("Images", Image.objects.count()),
            ("Bounding boxes", BoundingBox.objects.count()),
            ("Users", User.objects.count()),
        ]:
            self.stdout.write(f"  {label:<18} {count}")

    # ------------------------------------------------------------------ helpers

    def _flush(self):
        self.stdout.write("Flushing ALL images, uploads, bounding boxes and locations from the local database...")
        BoundingBox.objects.all().delete()
        Image.objects.all().delete()
        Upload.objects.all().delete()
        CameraStation.objects.all().delete()
        MicroSite.objects.all().delete()
        MacroSite.objects.all().delete()
        County.objects.all().delete()
        Area.objects.all().delete()
        Grid.objects.all().delete()

        # Annotator.human is a PROTECT foreign key, so any seeded user who has
        # actually annotated something has an Annotator row that blocks the delete
        # below. Clear those first, otherwise a second --flush raises ProtectedError.
        seeded_users = User.objects.filter(email__endswith="@wildepod.local").exclude(is_superuser=True)
        Annotator.objects.filter(human__in=seeded_users).delete()
        seeded_users.delete()

    def _create_species(self):
        names = []
        for common, scientific, group in SPECIES:
            obj, _ = SpeciesName.objects.get_or_create(
                name=common,
                defaults={"scientific_name": scientific, "species_group": group, "active": True},
            )
            names.append(obj)
        self.stdout.write(f"Species names: {len(names)}")
        return names

    def _create_activity_types(self):
        for name in ANIMAL_ACTIVITIES:
            ActivityType.objects.get_or_create(name=name, defaults={"category": "animal"})
        for name in HUMAN_ACTIVITIES:
            ActivityType.objects.get_or_create(name=name, defaults={"category": "human"})
        self.stdout.write(f"Activity types: {ActivityType.objects.count()}")

    def _create_volunteers(self):
        people = [
            ("Ana Ramirez", "ana@wildepod.local", False, False),
            ("Ben Okafor", "ben@wildepod.local", False, False),
            ("Chris Lindqvist", "chris@wildepod.local", True, False),
            ("Dana Whitfield", "dana@wildepod.local", False, True),
        ]
        volunteers = []
        for name, email, is_staff, is_expert in people:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "name": name,
                    "is_staff": is_staff,
                    "is_expert": is_expert,
                    "is_volunteer": True,
                    "is_active": True,
                },
            )
            if created:
                # A shared, committed password is deliberate here, and is not the pattern
                # #534 removes. That change concerns a *superuser* password baked into
                # local_setup.sh. These are throwaway volunteer accounts, created only on
                # a SQLite database (handle() refuses any other backend) and holding only
                # synthetic data. The README documents this value so a new developer can
                # log in; randomising or env-gating it would add setup friction without
                # protecting anything.
                user.set_password("wildepod-local-dev")
                user.save()
            volunteers.append(user)
        self.stdout.write(f"Volunteers: {len(volunteers)} (password: wildepod-local-dev)")
        return volunteers

    def _create_locations(self, station_count):
        area, _ = Area.objects.get_or_create(name="San Francisco Bay Area")
        county, _ = County.objects.get_or_create(name="Marin", defaults={"area": area})
        macro, _ = MacroSite.objects.get_or_create(name="Mount Tamalpais", defaults={"county": county})
        grid, _ = Grid.objects.get_or_create(name="TAM-01")
        micro, _ = MicroSite.objects.get_or_create(name="Redwood Creek", defaults={"macro_site": macro, "grid": grid})

        stations = []
        for i in range(station_count):
            station, _ = CameraStation.objects.get_or_create(
                station_id=f"TAM-{i + 1:03d}",
                defaults={
                    "micro_site": micro,
                    "latitude": round(37.9235 + random.uniform(-0.05, 0.05), 6),
                    "longitude": round(-122.5965 + random.uniform(-0.05, 0.05), 6),
                    "date_deployed": date.today() - timedelta(days=random.randint(120, 400)),
                },
            )
            stations.append(station)
        self.stdout.write(f"Camera stations: {len(stations)} under {macro.name} / {micro.name}")
        return stations

    def _create_bot_annotator(self):
        bot, _ = Bot.objects.get_or_create(
            name="MegaDetector",
            version="v5a.0.0",
            defaults={"task_type": "Object Detection", "threshold": 0.2},
        )
        annotator, _ = Annotator.objects.get_or_create(type="bot", bot=bot, human=None)
        return annotator

    def _make_placeholder(self, index, label):
        """Write a placeholder JPEG into MEDIA_ROOT and return its relative path."""
        media_root = Path(settings.MEDIA_ROOT)
        (media_root / "thumbnails").mkdir(parents=True, exist_ok=True)

        rel_path = f"thumbnails/seed_{index:04d}.jpg"
        abs_path = media_root / rel_path

        img = PILImage.new("RGB", (1024, 768), PALETTE[index % len(PALETTE)])
        draw = ImageDraw.Draw(img)
        # Rough horizon + a few trunks so frames don't read as flat colour swatches.
        draw.rectangle([0, 520, 1024, 768], fill=(58, 54, 44))
        for x in range(60, 1024, 190):
            draw.rectangle([x, 180, x + 26, 540], fill=(48, 42, 34))
        draw.text((28, 24), f"WildePod sample frame {index:04d}", fill=(235, 235, 225))
        draw.text((28, 48), label, fill=(210, 210, 200))
        img.save(abs_path, "JPEG", quality=70)
        return rel_path

    def _create_images(self, image_count, stations, volunteers, bot_annotator, species_names):
        last_action, _ = CameraStationAction.objects.get_or_create(action="SD card swapped, camera left in place")

        uploads = []
        for i, station in enumerate(stations):
            # Alternate upload_method so both branches of the Finalize page are
            # reachable locally: "E" renders the external-request-link variant,
            # "D" renders the direct-Dropbox variant with the 2FA button.
            method = "D" if i % 2 else "E"
            upload = Upload.objects.create(
                camera_station=station,
                date_retrieved=timezone.now() - timedelta(days=random.randint(1, 45)),
                last_action=last_action,
                volunteer=random.choice(volunteers),
                upload_method=method,
                upload_complete=False,
                dropbox_folder_name=f"TAM_{station.station_id}_seed",
                dropbox_folder_path=f"/seed/{station.station_id}",
                dropbox_request_id=f"seed-req-{i}",
                dropbox_request_url=f"https://example.invalid/request/{i}",
                dropbox_direct_url=(
                    f"https://example.invalid/dropbox/seed-{station.station_id}" if method == "D" else None
                ),
            )
            uploads.append(upload)

        created = 0
        for i in range(image_count):
            upload = uploads[i % len(uploads)]
            station = upload.camera_station
            label = f"{station.station_id}"
            thumb = self._make_placeholder(i, label)

            image = Image.objects.create(
                upload=upload,
                dropbox_file_path=f"/seed/{station.station_id}/IMG_{i:04d}.jpg",
                dropbox_file_name=f"IMG_{i:04d}.jpg",
                dropbox_file_path_display=f"/seed/{station.station_id}/IMG_{i:04d}.jpg",
                dropbox_content_hash=f"seedhash{i:056d}",
                dropbox_file_id=f"id:seed{i}",
                file_size=random.randint(400_000, 3_500_000),
                trigger_timestamp=timezone.now() - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23)),
                thumbnail_gcloud_path=thumb,
                latitude=station.latitude,
                longitude=station.longitude,
                # Flags that make the image eligible for the species annotation queue.
                # use_precomputed_flags marks the image as preprocessed; without it
                # species_pipeline_query() filters the image out entirely.
                use_precomputed_flags=True,
                has_bbox_above_confidence_threshold=True,
                has_uncertain_bbox=True,
                has_animals=True,
                has_wild_animals=True,
                category_pipeline_complete=True,
                species_pipeline_complete=False,
                activity_pipeline_complete=False,
                staff_review_needed=False,
                image_reported=False,
            )

            # MegaDetector-style detections: one or two boxes per frame.
            for _ in range(random.randint(1, 2)):
                x = round(random.uniform(0.05, 0.6), 4)
                y = round(random.uniform(0.05, 0.6), 4)
                bbox = BoundingBox.objects.create(
                    image=image,
                    x=x,
                    y=y,
                    w=round(random.uniform(0.12, 0.3), 4),
                    h=round(random.uniform(0.12, 0.3), 4),
                    confidence=round(random.uniform(0.55, 0.98), 4),
                    confidence_threshold=0.2,
                    created_by=bot_annotator,
                )
                Category.objects.create(
                    bounding_box=bbox,
                    name="animal",
                    confidence=bbox.confidence,
                    created_by=bot_annotator,
                )
            created += 1

        self.stdout.write(f"Images: {created} across {len(uploads)} uploads (placeholders in {settings.MEDIA_ROOT})")
