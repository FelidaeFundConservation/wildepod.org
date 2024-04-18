import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
import yolov9
from colorama import Back, Fore, Style
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Case, Exists, F, OuterRef, Prefetch, Q, When
from images.models import Annotator, BoundingBox, Category, Image
from images.views.annotation import (
    calculateActivityAnnotationFlags,
    calculateCategoryAnnotationFlags,
    calculateSpeciesAnnotationFlags,
)
from PIL import Image as PILImage
from pyexpat import model


def get_pil_image(image_url):
    response = requests.get(f"https://storage.googleapis.com/{settings.GS_BUCKET_NAME}/media/{image_url}")

    pillow_image = None

    if response.status_code == 200:
        # Get the image data
        pillow_image = PILImage.open(BytesIO(response.content)).convert("RGB")

    return pillow_image


class Command(BaseCommand):
    help = "Update images flags and detect species."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model_name",
            nargs="?",
            type=str,
            default=None,
            help="The yolov9 model name. Enables species AI detections.",
        )
        parser.add_argument("--make_changes", action="store_true", help="Flag to enable saving the changes.")
        parser.add_argument(
            "--camera_station", type=str, default=None, nargs="?", help="Camera station to filter images by."
        )
        parser.add_argument(
            "--macrosite", type=str, default=None, nargs="?", help="Camera station to filter images by."
        )

    def handle(self, *args, **options):
        model_name = options.get("model_name")
        camera_station = options.get("camera_station")
        macrosite = options.get("macrosite")

        print("\n================================")
        if options.get("make_changes"):
            print(
                f"NOTE: {Fore.GREEN}Changes are enabled.{Style.RESET_ALL} Calculations will be applied to image objects."
            )
        else:
            print(Fore.YELLOW + "NOTE: Changes are not enabled. Calculations will not be applied.")

        if model_name:
            print(f"NOTE: {Fore.GREEN}Species AI detection enabled{Style.RESET_ALL} - using model '{model_name}.pt'")
            model = yolov9.load(model_name)

            def detect_species(image_url):
                if image_url:
                    model.conf = 0.1  # NMS confidence threshold
                    model.iou = 0.45  # NMS IoU threshold
                    model.agnostic = False  # NMS class-agnostic
                    model.multi_label = False  # NMS multiple labels per box
                    model.max_det = 100  # maximum number of detections per image

                    results = model(get_pil_image(image_url))

                    predictions = results.pred[0]
                    boxes = predictions[:, :4]  # x1, y1, x2, y2
                    scores = predictions[:, 4]
                    categories = predictions[:, 5]

                    classes = results.pandas().xyxy[0]["name"].tolist()

                    return classes

        else:
            print(Fore.YELLOW + "NOTE: No species detection model provided. AI detections will not be run.")
        print("================================\n")

        image_count = 0
        image_count_lock = threading.Lock()
        chunk_size = 100
        MAX_THREADS = 10

        start_time = time.time()

        def process_image(image):
            nonlocal image_count
            # Handles all checks and flag setting.
            calculateCategoryAnnotationFlags(image)
            calculateSpeciesAnnotationFlags(image)
            calculateActivityAnnotationFlags(image)

            if model_name:
                try:
                    image.species_ai_detections = detect_species(image.thumbnail_gcloud_path)
                except:
                    pass

            with image_count_lock:
                image_count += 1
            if (image_count % 50) == 0:
                completion_percentage = (image_count / total_image_count) * 100

                print(
                    f"{Fore.YELLOW}\n==================================="
                    f"{Fore.YELLOW}\nOperation Status ({completion_percentage:.2f}%)"
                    f"{Fore.YELLOW}\n==================================={Style.RESET_ALL}"
                    f"\nTime elapsed: {time.time() - start_time:.2f} seconds"
                    f"\nImages checked: {image_count} of {total_image_count}"
                    f"\nExample detections: {image.species_ai_detections}"
                    f"\nExample Image: https://wildepod.org/images/image/{image.id}"
                    f"\n",
                    end="\r",
                    flush=True,
                )

            if options.get("make_changes"):
                image.use_precomputed_flags = True
                image.save()
            else:
                image = None

        kwargs = {}

        if camera_station is not None:
            kwargs["upload__camera_station__station_id__icontains"] = camera_station
            print(f"Camera Station: {camera_station}")
        if macrosite is not None:
            kwargs["upload__camera_station__micro_site__macro_site__name__icontains"] = macrosite
            print(f"Macrosite: {macrosite}")

        print(f"\nQuerying images... please wait a moment...\n")

        # NOTE: Change this query as needed if provided args aren't enough
        images_tally = (
            Image.objects.filter(
                Exists(
                    BoundingBox.objects.filter(image=OuterRef("pk"))
                    .annotate(
                        confidence_threshold=Case(
                            When(created_by__type="bot", then="created_by__bot__threshold"),
                            default=0.0,
                        ),
                    )
                    .filter(
                        confidence__gte=F("confidence_threshold"),
                    )
                ),
                use_precomputed_flags=False,
                **kwargs,
            )
            .distinct()
            .order_by("-upload__priority", "trigger_timestamp")
        )

        images = images_tally.iterator(chunk_size=chunk_size)

        total_image_count = images_tally.count()
        print(f"Gathered {Fore.GREEN}{total_image_count}{Style.RESET_ALL} images to be updated.\n")

        print(f"Starting migration... please wait a moment...\n")

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            image_chunk = []
            for image in images:
                image_chunk.append(image)

                if len(image_chunk) == chunk_size:
                    list(executor.map(process_image, image_chunk))
                    image_chunk = []

            # Process any remaining images in the last chunk
            if image_chunk:
                list(executor.map(process_image, image_chunk))
