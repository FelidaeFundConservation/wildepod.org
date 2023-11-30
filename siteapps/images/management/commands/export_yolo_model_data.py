import logging
from io import BytesIO

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from images.models import Image, Species, SpeciesName
from PIL import Image as PILImage


class Command(BaseCommand):
    help = "Gather data from database and create YOLO data."

    def handle(self, *args, **options):
        try:
            IMAGE_COUNT = 1000
            PATH = "./siteapps/images/management/commands/export/"

            logging.info(f"Gathering data from {IMAGE_COUNT} images...")

            images = Image.objects.filter(has_wild_animals=True)[:IMAGE_COUNT]

            split_index = int(len(images) * 0.7)

            training = images[:split_index]
            validation = images[split_index:]

            def get_data(images, directory):
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
                                        Q(created_by__human__is_staff=True)
                                        | Q(created_by__human__is_expert=True)
                                        | Q(accepted_by__human__is_staff=True)
                                        | Q(accepted_by__human__is_expert=True),
                                        bounding_box=bbox,
                                    )
                                    .distinct()
                                    .first()
                                )

                                if species:
                                    info = f"{species.name.id} {bbox.x + (bbox.w / 2)} {bbox.y + (bbox.h / 2)} {bbox.w} {bbox.h}\n"
                                    print(info)
                                    file.write(info)

            get_data(training, "train")
            get_data(validation, "val")

            with open(f"{PATH}config.yaml", "w+") as file:
                classes = list(SpeciesName.objects.all().values("id"))

                classes_list = []
                for species in classes:
                    classes_list.append(str(species["id"]))

                lines = [
                    "path: ./\n",
                    "train: ./wildepod/images/train/\n",
                    "test: ./wildepod/images/test/\n",
                    "val: ./wildepod/images/val/\n",
                    "\n",
                    f"nc: {len(classes_list)}\n",
                    "\n",
                    f"names: {str(classes_list)}\n",
                ]
                file.writelines(lines)

        except Exception as e:
            raise CommandError(e)
