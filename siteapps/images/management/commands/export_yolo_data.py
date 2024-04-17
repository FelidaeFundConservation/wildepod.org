import logging
import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from images.models import Image, Species, SpeciesName
from PIL import Image as PILImage


class Command(BaseCommand):
    help = "Gather data from database and create YOLO data."

    def add_arguments(self, parser):
        parser.add_argument("--split", type=float, default=0.7, help="Training-validation split percentage."),
        parser.add_argument("--limit", type=int, default=10000, help="Limit data per-species to this number.")

    def handle(self, *args, **options):
        split = options.get("split")
        limit = options.get("limit")

        try:
            PATH = "./siteapps/images/management/commands/export/"
            os.makedirs(PATH, exist_ok=True)

            logging.info(f"Gathering data from images...")

            speciesname_list = SpeciesName.objects.filter(~Q(name="Unknown"))

            training = []
            validation = []

            for name in speciesname_list:
                name_results = (
                    Image.objects.filter(
                        boundingbox__species__name__id=name.id,
                    )
                    .distinct()
                    .order_by("?")
                )[:limit]

                split_index = int(len(name_results) * split)

                training += name_results[:split_index]
                validation += name_results[split_index:]

                print(f"Got {len(name_results)} images for class {name.name}.")

            with open(f"{PATH}config.yaml", "w+") as file:
                classes = list(SpeciesName.objects.all())

                classes_list = []
                classes_dict = {}

                classIndex = 0

                for species in classes:
                    classes_list.append(f"  {classIndex}: '{species.name}'\n")
                    classes_dict[f"{species.name}"] = classIndex
                    classIndex += 1

                lines = [
                    "path: ./\n",
                    "train: ./wildepod/images/train/\n",
                    "test: ./wildepod/images/test/\n",
                    "val: ./wildepod/images/val/\n",
                    "\n",
                    f"nc: {len(classes_list)}\n",
                    "\n",
                    f"names: \n",
                ]

                lines += classes_list

                file.writelines(lines)

            training_len = len(training)
            validation_len = len(validation)
            total_count = training_len + validation_len

            print(f"Total images: {training_len + validation_len}")
            print(f"Training: {training_len}")
            print(f"Validation: {validation_len}")

            input("Do you want to retrieve this data? [ENTER]")

            print("\nRetriving images... please wait a moment...")

            def get_data(image, directory):
                image_file_path = f"{settings.MEDIA_URL}{image.thumbnail_gcloud_path}"
                response = requests.get(image_file_path)

                if response.status_code == 200:
                    pillow_image = PILImage.open(BytesIO(response.content)).convert("RGB")
                    pillow_image.save(f"{PATH}/datasets/wildepod/images/{directory}/{image.id}.jpg", "JPEG")
                    with open(f"{PATH}/datasets/wildepod/labels/{directory}/{image.id}.txt", "w+") as file:
                        for bbox in image.boundingbox_set.valid().all():
                            species = (
                                Species.objects.filter(
                                    bounding_box=bbox,
                                )
                                .distinct()
                                .first()
                            )

                            if species:
                                info = f"{classes_dict.get(f'{species.name.name}')} {bbox.x + (bbox.w / 2)} {bbox.y + (bbox.h / 2)} {bbox.w} {bbox.h}\n"
                                file.write(info)

                nonlocal total_count

                total_count -= 1
                if total_count % 100 == 0:
                    print(
                        f"\n===================================\n"
                        f"{total_count} images remaining.\n"
                        f"===================================\n"
                        f"Example info: {info}",
                        end="\r",  # Prevents newline
                        flush=True,  # Flushes the buffer
                    )

            with ThreadPoolExecutor(max_workers=10) as executor:
                for image in training:
                    executor.submit(get_data, image, "train")
                    os.makedirs(f"{PATH}/datasets/wildepod/images/train/", exist_ok=True)
                    os.makedirs(f"{PATH}/datasets/wildepod/labels/train/", exist_ok=True)

                for image in validation:
                    executor.submit(get_data, image, "val")
                    os.makedirs(f"{PATH}/datasets/wildepod/images/val/", exist_ok=True)
                    os.makedirs(f"{PATH}/datasets/wildepod/labels/val/", exist_ok=True)

        except Exception as e:
            raise CommandError(e)
