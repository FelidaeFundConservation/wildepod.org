import logging
from io import BytesIO
from random import random

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from images.models import Image, Species, SpeciesName
from PIL import Image as PILImage
from datetime import datetime

class Command(BaseCommand):
    help = "Gather data from database and create YOLO data."

    def handle(self, *args, **options):
        try:
            PATH = "./siteapps/images/management/commands/export/"    

            logging.info(f"Gathering data from images...")
            
            cutoff_date = datetime(year=2023, month=12, day=4, hour=0, minute=0, second=0)

            speciesname_list = SpeciesName.objects.filter(~Q(name="Unknown"))

            training = []
            validation = []
            
            for name in speciesname_list:
                name_results = (
                    Image.objects.filter(
                        # Q(has_wild_animals=True)
                        # | Q(species_checked_by__human__is_staff=True)
                        # | Q(species_checked_by__human__is_expert=True),
                        boundingbox__species__name__id=name.id,
                        boundingbox__modified__gte=cutoff_date
                    )
                    .distinct()
                    .order_by("?")
                )  
                
                split_index = int(len(name_results) * 0.7)
                
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


            print(f"Total images: {len(training) + len(validation)}")
            print(f"Training: {len(training)}")
            print(f"Validation: {len(validation)}")

            input("Do you want to retrieve this data? [ENTER]")

            def get_data(images, directory):
                length = len(images)

                for image in images:
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
                                    print(f"{length} to go: {info}")
                                    file.write(info)
                    length -= 1

            get_data(training, "train")
            get_data(validation, "val")

        except Exception as e:
            raise CommandError(e)
