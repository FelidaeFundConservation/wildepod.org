import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO

import requests
from colorama import Back, Fore, Style
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Case, Exists, F, OuterRef, Prefetch, Q, When
from images.models import Annotator, Bot, BoundingBox, Category, Image, Upload
from images.views import activity_pipeline_query, species_pipeline_query
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
            "--category_model",
            nargs="?",
            type=str,
            default=None,
            help="The yolov5 model name. Enables bbox AI detections.",
        )
        parser.add_argument(
            "--species_model",
            nargs="?",
            type=str,
            default=None,
            help="The yolov9 model name. Enables species AI detections.",
        )
        parser.add_argument("--make_changes", action="store_true", help="Flag to enable saving the changes.")

    def handle(self, *args, **options):
        species_model = options.get("species_model")
        category_model = options.get("category_model")
        print("\n================================")
        if options.get("make_changes"):
            print(
                f"NOTE: {Fore.GREEN}Changes are enabled.{Style.RESET_ALL} Calculations will be applied to image objects."
            )
        else:
            print(Fore.YELLOW + "NOTE: Changes are not enabled. Calculations will not be applied.")

        ########################
        # Species Detection
        ########################

        if species_model:
            print(f"NOTE: {Fore.GREEN}Species AI detection enabled{Style.RESET_ALL} - using model '{species_model}.pt'")
            import yolov9

            sp_model = yolov9.load(species_model)
            sp_model.conf = 0.1  # NMS confidence threshold
            sp_model.iou = 0.45  # NMS IoU threshold
            sp_model.agnostic = False  # NMS class-agnostic
            sp_model.multi_label = False  # NMS multiple labels per box
            sp_model.max_det = 100  # maximum number of detections per image

            def detect_species(image):
                image_url = image.thumbnail_gcloud_path

                if image_url:
                    results = sp_model(get_pil_image(image_url))

                    predictions = results.pred[0]
                    boxes = predictions[:, :4]  # x1, y1, x2, y2
                    scores = predictions[:, 4]
                    categories = predictions[:, 5]

                    classes = results.pandas().xyxy[0]["name"].tolist()

                    image.species_ai_detections = classes
                    image.save()

                    return classes

        else:
            print(Fore.YELLOW + "NOTE: No species detection model provided. AI detections will not be run.")

        ########################
        # Category Detection
        ########################
        if category_model:

            def setup_category_inference():
                print(
                    f"NOTE: {Fore.GREEN}Category AI detection enabled{Style.RESET_ALL} - using model '{category_model}.pt'"
                )
                import yolov5

                bot = Bot.objects.get(name="MegaDetector", version="v5a.0.0")

                ct_model = yolov5.load(category_model + ".pt")
                ct_model.conf = 0.1  # NMS confidence threshold
                ct_model.iou = 0.45  # NMS IoU threshold
                ct_model.agnostic = False  # NMS class-agnostic
                ct_model.multi_label = False  # NMS multiple labels per box
                ct_model.max_det = 100  # maximum number of detections per image

                def detect_bboxes(image):
                    image_url = image.thumbnail_gcloud_path

                    if image_url:
                        pil_img = get_pil_image(image_url)

                    nonlocal ct_model
                    if pil_img and ct_model:
                        results = ct_model(pil_img)

                        df = results.pandas().xyxy[0]

                        categories = df["name"].tolist()
                        confidences = df["confidence"].tolist()
                        xmins = df["xmin"].tolist()
                        xmaxs = df["xmax"].tolist()
                        ymins = df["ymin"].tolist()
                        ymaxs = df["ymax"].tolist()

                        bounding_box_data = [
                            {
                                "image": image,
                                "confidence": confidence,
                                "x": xmin,
                                "y": ymin,
                                "w": xmax - xmin,
                                "h": ymax - ymin,
                                "created_by": bot,
                                "confidence_threshold": bot.threshold,
                            }
                            for category, confidence, xmin, ymin, xmax, ymax in zip(
                                categories, confidences, xmins, ymins, xmaxs, ymaxs
                            )
                        ]

                        for kwargs in bounding_box_data:
                            bounding_box, created = BoundingBox.objects.get_or_create(**kwargs)
                            category, created = Category.objects.get_or_create(
                                bounding_box=bounding_box, category=category
                            )

                        image.processed = True
                        image.save()

                return detect_bboxes

            detect_bboxes = setup_category_inference()
        else:
            print(Fore.YELLOW + "NOTE: No bbox detection model provided. AI detections will not be run.")
        print("================================\n")

        image_count = 0
        image_count_lock = threading.Lock()
        chunk_size = 100
        MAX_THREADS = 10

        start_time = time.time()

        def process_image(image):
            nonlocal image_count

            # Set context images
            image.context_image_gcloud_paths = list(
                Image.objects.filter(
                    upload=image.upload,
                    upload__camera_station=image.upload.camera_station,
                    trigger_timestamp__lt=image.trigger_timestamp,
                    trigger_timestamp__gt=image.trigger_timestamp - timedelta(minutes=10),
                ).values_list("thumbnail_gcloud_path", flat=True)[:20]
            ) + list(
                Image.objects.filter(
                    upload=image.upload,
                    upload__camera_station=image.upload.camera_station,
                    trigger_timestamp__gte=image.trigger_timestamp,
                    trigger_timestamp__lt=image.trigger_timestamp + timedelta(minutes=10),
                ).values_list("thumbnail_gcloud_path", flat=True)[:20]
            )

            if species_model:
                try:
                    image.species_ai_detections = detect_species(image)

                    # Set if the image has AI detected cats
                    if image.species_ai_detections:
                        image.has_cats = (
                            "Puma" in image.species_ai_detections or "Bobcat" in image.species_ai_detections
                        )
                except:
                    pass
            if category_model:
                try:
                    detect_bboxes(image)
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
                    f"\nLast image: {image.id}"
                    f"\nDetections: {image.boundingbox_set.all().values_list('category__name')} {image.species_ai_detections}"
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

        print(f"\nQuerying images... please wait a moment...\n")

        # NOTE: Change this query as needed if provided args aren't enough
        if category_model:
            images_tally = Image.objects.filter(upload__processed=False).exclude(
                Q(thumbnail_gcloud_path=None) | Q(trigger_timestamp=None)
            )
        elif species_model:
            images_tally = Image.objects.filter(species_ai_detections=None).exclude(
                Q(thumbnail_gcloud_path=None) | Q(trigger_timestamp=None)
            )

        images = images_tally.iterator(chunk_size=chunk_size)

        total_image_count = images_tally.count()
        print(f"Gathered {Fore.GREEN}{total_image_count}{Style.RESET_ALL} images to be processed.\n")

        print(f"Starting inference... please wait a moment...\n")

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

        upload_objs = Upload.objects.filter(processed=False)

        for upload in upload_objs:
            if not upload.images.filter(processed=False).exists():
                upload.processed = True
                upload.save()

                print(f"Upload {upload.id} marked as processed.")
