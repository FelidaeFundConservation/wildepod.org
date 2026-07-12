# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from io import BytesIO

import dropbox
import requests
import torch as _torch
from colorama import Back, Fore, Style
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Case, Exists, F, OuterRef, Prefetch, Q, When
from images.models import Annotator, Bot, BoundingBox, Category, Image, Upload
from images.processors.image import add_thumbnail
from images.processors.upload import (
    check_image_valid,
    get_dropbox_file_listing,
    get_metadata_with_retry,
    preretrieve_file_metadata,
)
from images.views import activity_pipeline_query, species_pipeline_query
from images.views.annotation import (
    calculateActivityAnnotationFlags,
    calculateCategoryAnnotationFlags,
    calculateSpeciesAnnotationFlags,
)
from PIL import Image as PILImage

# Save original
_original_torch_load = _torch.load


def patched_torch_load(*args, **kwargs):
    # Force old behavior
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


# Patch it
_torch.load = patched_torch_load


def get_pil_image(image_url):
    response = requests.get(f"https://storage.googleapis.com/{settings.GS_BUCKET_NAME}/media/{image_url}")

    pillow_image = None

    if response.status_code == 200:
        # Get the image data
        pillow_image = PILImage.open(BytesIO(response.content)).convert("RGB")

    return pillow_image


def process_entry(entry, preretrieved_metadata, upload):
    if not isinstance(entry, dropbox.files.FileMetadata):
        return None

    # Retrieve metadata with retry
    response = get_metadata_with_retry(preretrieved_metadata, entry, max_retries=10, delay=10)

    # Get media info
    try:
        media_info = response.media_info.get_metadata()
    except Exception as error:
        print("Metadata error:", error, flush=True)
        return None

    # Only process images/videos
    if not isinstance(media_info, (dropbox.files.PhotoMetadata, dropbox.files.VideoMetadata)):
        return None

    img_obj, created = Image.objects.get_or_create(
        upload=upload,
        dropbox_file_name=response.name,
        dropbox_file_path=response.path_lower,
        dropbox_file_path_display=response.path_display,
        dropbox_content_hash=response.content_hash,
        dropbox_file_id=response.id,
        file_size=response.size,
        is_video=isinstance(media_info, dropbox.files.VideoMetadata),
    )

    if created:
        if media_info.time_taken:
            img_obj.trigger_timestamp = media_info.time_taken
        if media_info.dimensions:
            img_obj.height = media_info.dimensions.height
            img_obj.width = media_info.dimensions.width
        if media_info.location:
            img_obj.latitude = media_info.location.latitude
            img_obj.longitude = media_info.location.longitude
        if img_obj.is_video and media_info.duration:
            img_obj.duration = media_info.duration
        img_obj.save()

    if not img_obj.thumbnail_gcloud_path:
        add_thumbnail(img_obj)

    # Remove corrupted images
    if not img_obj.processed and not img_obj.is_video:
        if check_image_valid(img_obj) == False:
            img_obj.delete()
            return "deleted"

    return img_obj.id


def create_entries(upload, max_workers=15):
    entries = get_dropbox_file_listing(upload.dropbox_folder_path)
    print(len(entries), "entries found total.", flush=True)

    existing_paths = {
        path.rsplit(".", 1)[0] for path in upload.images.all().values_list("dropbox_file_path", flat=True)
    }

    filtered_entries = [entry for entry in entries if entry.path_lower.rsplit(".", 1)[0] not in existing_paths]

    print(len(filtered_entries), "entries remaining to process. Getting metadata...", flush=True)

    preretrieved_metadata = {}
    preretrieve_file_metadata(filtered_entries, preretrieved_metadata)
    print("All metadata retrieved. Starting processing...", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_entry, entry, preretrieved_metadata, upload) for entry in filtered_entries]
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print("Error in worker:", e, flush=True)

    return results


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

        parser.add_argument(
            "--add_thumbnails",
            action="store_true",
            help="Pull from dropbox and create image objs.",
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
                annotator = Annotator.objects.get(type="bot", bot=bot)

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

                        img_width, img_height = pil_img.size

                        bounding_box_data = [
                            {
                                "image": image,
                                "confidence": confidence,
                                "x": xmin / img_width,
                                "y": ymin / img_height,
                                "w": (xmax - xmin) / img_width,
                                "h": (ymax - ymin) / img_height,
                                "created_by": annotator,
                                "confidence_threshold": bot.threshold,
                                "category": category,
                            }
                            for category, confidence, xmin, ymin, xmax, ymax in zip(
                                categories, confidences, xmins, ymins, xmaxs, ymaxs
                            )
                        ]

                        for kwargs in bounding_box_data:
                            category = kwargs.pop("category")
                            bounding_box, created = BoundingBox.objects.get_or_create(**kwargs)

                            cats = Category.objects.filter(
                                bounding_box=bounding_box,
                                name=category,
                                created_by=annotator,
                            )
                            first_cat = cats.first()
                            if first_cat:
                                cats.exclude(id=first_cat.id).delete()

                            category_obj, created = Category.objects.get_or_create(
                                bounding_box=bounding_box,
                                name=category,
                                created_by=annotator,
                            )
                            category_obj.confidence = round(kwargs["confidence"], 2)
                            category_obj.save()

                        if options.get("make_changes"):
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
                except Exception as e:
                    print(e)

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

        print(f"\Creating images... please wait a moment...\n")
        if options.get("add_thumbnails"):
            unprocessed = Upload.objects.filter(processed=False, upload_complete=True, deleted=False).order_by(
                "img_count"
            )

            for upload_obj in unprocessed:
                print(f"Pre-processing upload - {upload_obj.id}")
                print(f"{Image.objects.filter(upload=upload_obj).count()} images in upload before preprocess")
                try:
                    results = create_entries(upload_obj)
                except Exception as e:
                    print(f"Error processing upload {upload_obj} - {e}")
                print(f"{Image.objects.filter(upload=upload_obj).count()} images in upload after preprocess")

        print(f"\nQuerying images to run inference... please wait a moment...\n")

        # NOTE: Change this query as needed if provided args aren't enough
        if category_model:
            images_tally = Image.objects.filter(
                processed=False, upload__upload_complete=True, category_pipeline_complete=False
            ).exclude(Q(thumbnail_gcloud_path=None) | Q(trigger_timestamp=None))
        elif species_model:
            images_tally = Image.objects.filter(species_ai_detections=None, upload__upload_complete=True).exclude(
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

        upload_objs = Upload.objects.filter(processed=False, upload_complete=True, deleted=False)

        for upload in upload_objs:
            unprocessed_imgs = upload.images.filter(processed=False)

            if not unprocessed_imgs.exists():
                upload.processed = True
                upload.save()

                print(f"Upload {upload.id} marked as processed.")
            else:
                print(f"Upload {upload.id} has {unprocessed_imgs.count()} unprocessed images.")

                # Try one more time
                for image in unprocessed_imgs:
                    try:
                        add_thumbnail(image)
                    except Exception as e:
                        print(f"Cannot create thumbnail - deleting - {e}")
                        image.delete()

                    unprocessed_imgs = upload.images.filter(processed=False)

                    if not unprocessed_imgs.exists():
                        upload.processed = True
                        upload.save()

                        print(f"Upload {upload.id} marked as processed.")
