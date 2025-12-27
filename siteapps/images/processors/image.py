import logging
import os
from io import BytesIO

import dropbox
import google.auth.transport.requests
import google.oauth2.id_token
import requests
from django.conf import settings
from django.db.models import F, Q
from images.models import Annotator, Bot, BoundingBox, Category, Image
from images.utils.dropbox_client import create_dropbox_client
from my_utils.storages import MediaRootGoogleCloudStorage
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Dropbox client is now created on-demand via create_dropbox_client() function
# imported from processors module

# Create a storage object instance
storage = MediaRootGoogleCloudStorage()

# Retry strategy for calling megadetector cloud function
md_retry_strategy = Retry(
    total=5,
    # Setting allowed methods to false will retry on all methods
    # https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html?highlight=retry#urllib3.util.Retry
    allowed_methods=False,
    status_forcelist=[400, 408, 429, 500, 502, 503, 504],
    # Since the cloud function is slow, backoff is set to a large value
    # 120 should give values of 1min, 2mins, 4mins, 8mins and 16mins
    backoff_factor=120,
)
adapter = HTTPAdapter(max_retries=md_retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

MEGADETECTOR_LABEL_MAP = {"1": "animal", "2": "person", "3": "vehicle"}


def has_bbox_above_confidence_threshold(image):
    return image.boundingbox_set.filter(
        ~Q(validity__in=["INVALID", None]), image=image, confidence__gte=F("confidence_threshold")
    ).exists()


# Function to save the thumbnails of the image
# This function is run for every valid image uploaded into dropbox
def add_thumbnail(image: Image, dbx=None):
    """Function to retrieve thumbnails from dropbox and save it into google buckets for serving

    Returns the full storage url
    """
    if dbx is None:
        dbx = create_dropbox_client()

    if dbx is None:
        logging.warning("Dropbox client not configured, skipping thumbnail retrieval")
        return

    logging.info("Retrieving thumbnail from dropbox..")
    # TODO: Handle error or Rollback on failure
    # Get a 1024x1024 thumbnail from dropbox.
    # This resolution should also work well for most ML models trained on top of resnet etc.
    metadata, response = dbx.files_get_thumbnail_v2(
        dropbox.files.PathOrLink(tag="path", value=image.dropbox_file_path),
        format=dropbox.files.ThumbnailFormat("jpeg", None),
        size=dropbox.files.ThumbnailSize("w1024h768", None),
        mode=dropbox.files.ThumbnailMode("bestfit", None),
    )
    logging.info("Successfully retrieved thumbnail from dropbox.")

    # Convert image binary to bytestream
    img_bytes = BytesIO(response.content)
    logging.info("Successfully converted thumbnail binary to bytestream.")

    target_path = f"thumbnails/1024/{image.dropbox_content_hash}.jpg"
    try:
        gcloud_path = storage.save(target_path, img_bytes)
        logging.info("Successfully saved thumbnail to google cloud storage.")
        image.thumbnail_gcloud_path = gcloud_path
        # Save the image
        image.save()
        logging.info("Successfully saved image object to database.")
    except Exception as e:
        logging.error(f"Error saving thumbnail to google cloud storage: {e}")
        return


def run_model_inference(image: Image, species: bool = False):
    """Function to add bounding boxes to an image using MegaDetector's object detection model"""
    # TODO: Handle error or Rollback on failure
    # Run MegaDetector on each image and create the relevant annotation objects
    # TODO: Probably a better way to handle this. Hardcoded for now. Might not even need a model/record for this
    try:
        bot = Bot.objects.get(name="MegaDetector", version="v5a.0.0")
        logging.info("Megadetector v5a.0.0 object detection bot already exists. Successfully retrieved.")
    except Bot.DoesNotExist:
        bot, created = Bot.objects.create(
            name="MegaDetector",
            version="v5a.0.0",
            task_type="Object Detection",
            model_api_url=f"{settings.MEGADETECTOR_URL}/annotate/",
        )
        logging.info("Megadetector v5a.0.0 object detection bot successfully created")

    annotator, created = Annotator.objects.get_or_create(type="bot", bot=bot)
    if created:
        logging.info("Megadetector annotator object successfully created")
    else:
        logging.info("Megadetector annotator object already exists. Successfully retrieved.")

    image_url = f"""https://storage.googleapis.com/{settings.GS_BUCKET_NAME}/media/{image.thumbnail_gcloud_path}"""

    # TODO: Gate cloud run behind auth & enable this over ungated calls
    # This is to prevent abuse of the API. Right now, the url obfuscation provides some protection

    # Currently there are issues with getting the id token and it is unclear why.
    # As a work around, at least in local mode, the ID token is simply yanked out from the env
    # export ID_TOKEN="$(gcloud auth print-identity-token -q)"
    if settings.LOCAL:
        id_token = os.environ.get("ID_TOKEN")
    else:
        # This is specifically to call the Megadetector API on Cloud Run that has auth gating.
        auth_req = google.auth.transport.requests.Request()

        if species:
            url = settings.SPECIES_DETECTOR_URL
        else:
            url = settings.MEGADETECTOR_URL

        id_token = google.oauth2.id_token.fetch_id_token(auth_req, url)

    # Check whether to detect category/bboxes or species
    if species:
        logging.info(f"Calling species detector on image with url - {image_url}")
        return detect_species(image=image, image_url=image_url, bot=bot, id_token=id_token, annotator=annotator)
    else:
        logging.info(f"Calling MegaDetector on image with url - {image_url}")
        add_bounding_boxes(image=image, image_url=image_url, bot=bot, id_token=id_token, annotator=annotator)


def detect_species(image: Image, image_url: str, bot: Bot, id_token: str, annotator: Annotator):
    logging.info("Sending POST request to species cloud run...")
    response = http.post(
        settings.SPECIES_DETECTOR_URL,
        json={
            "image": image_url,
            "detection_threshold": bot.threshold,
        },
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=300,
    )
    if response.status_code == 200:
        detections = response.json()["classes"]
        logging.info(f"""Species detector cloud run call successful. {len(detections)} species classes detected""")

        return detections
    else:
        raise Exception(f"Species detector cloud run failed with status code: {response.status_code}")


def extract_common_name(taxonomy_string):
    """Extract common name from taxonomy string.

    Example: 'febff896...;mammalia;artiodactyla;...;mule deer' -> 'mule deer'

    Args:
        taxonomy_string: Semicolon-separated taxonomy string

    Returns:
        Common name (last part of taxonomy) or 'unknown' if not found
    """
    if not taxonomy_string:
        return "unknown"
    parts = taxonomy_string.split(';')
    return parts[-1].strip() if parts else "unknown"


def run_speciesnet_inference(image: Image, image_url: str):
    """Function to run SpeciesNet inference on an image.

    SpeciesNet is an ensemble model that combines MegaDetector (for bounding boxes)
    and species classification in a single API call.

    Args:
        image: Image object to process
        image_url: URL to the image thumbnail in Google Cloud Storage

    Returns:
        tuple: (bounding_boxes_created, species_detections_list)
    """
    try:
        bot = Bot.objects.get(name="SpeciesNet", version="v4.0.2a")
        logging.info("SpeciesNet v4.0.2a bot already exists. Successfully retrieved.")
    except Bot.DoesNotExist:
        logging.error("SpeciesNet v4.0.2a bot does not exist. Please create it first.")
        raise

    annotator, created = Annotator.objects.get_or_create(type="bot", bot=bot)
    if created:
        logging.info("SpeciesNet annotator object successfully created")
    else:
        logging.info("SpeciesNet annotator object already exists. Successfully retrieved.")

    # Get authentication token
    if not settings.RUNNING_ON_APP_ENGINE:
        id_token = os.environ.get("ID_TOKEN")
    else:
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(auth_req, bot.model_api_url)

    logging.info(f"Calling SpeciesNet on image with url - {image_url}")

    # Download the image from GCS to upload to SpeciesNet
    # SpeciesNet expects multipart form-data file upload, not a URL
    logging.info("Downloading image from GCS for SpeciesNet upload...")
    image_response = requests.get(image_url, timeout=60)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image from GCS: {image_response.status_code}")

    # Prepare file upload
    image_bytes = BytesIO(image_response.content)
    files = {"file": (f"{image.dropbox_content_hash}.jpg", image_bytes, "image/jpeg")}

    # Call SpeciesNet API with file upload
    response = http.post(
        bot.model_api_url,
        files=files,
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=300,
    )

    if response.status_code != 200:
        raise Exception(f"SpeciesNet cloud run failed with status code: {response.status_code}")

    result = response.json()
    logging.info(f"""SpeciesNet call successful. Response received with {len(result.get("detections", []))} detections""")

    # Process detections (bounding boxes)
    detections = result.get("detections", [])
    for i, detection in enumerate(detections):
        # Create bounding box
        bounding_box, created = BoundingBox.objects.get_or_create(
            image=image,
            confidence=detection["conf"],
            x=detection["bbox"][0],
            y=detection["bbox"][1],
            w=detection["bbox"][2],
            h=detection["bbox"][3],
            created_by=annotator,
            confidence_threshold=bot.threshold,
        )
        if created:
            logging.info(
                f"""Successfully created bounding box for object #{i+1} - {detection.get("label", detection["category"])} (confidence - {detection["conf"]})"""
            )
        else:
            logging.info("Bounding box already exists. Successfully retrieved.")

        # Create category annotation
        category_name = MEGADETECTOR_LABEL_MAP.get(detection["category"], detection.get("label", "unknown"))
        category, _ = Category.objects.get_or_create(
            bounding_box=bounding_box,
            name=category_name,
            created_by=annotator,
            confidence=detection["conf"],
        )

    # Process species classifications
    classifications = result.get("classifications", {})
    classes = classifications.get("classes", [])

    # Extract common names from the top classes
    species_detections = [extract_common_name(cls) for cls in classes]

    logging.info(f"SpeciesNet identified {len(species_detections)} species classes")

    # Update image bbox flags
    image.has_bbox_above_confidence_threshold = has_bbox_above_confidence_threshold(image)
    image.has_uncertain_bbox = image.boundingbox_set.filter(validity="UNCERTAIN").exists()

    return len(detections), species_detections


def add_bounding_boxes(image: Image, image_url: str, bot: Bot, id_token: str, annotator: Annotator):
    response = http.post(
        bot.model_api_url,
        json={"image": image_url, "megadetector_version": bot.version, "detection_threshold": bot.threshold},
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=300,
    )

    # Call the MegaDetector cloud function
    # There is a really high timeout here since the cloud function takes a while to start on first request
    # response = http.post(bot.model_api_url, json={"image": image_url, "megadetector_version": bot.version}, timeout=300)
    if response.status_code == 200:
        result = response.json()["annotation"]
        logging.info(f"""MegaDetector cloud run call successful. {len(result["detections"])} objects detected""")
    else:
        raise Exception(f"MegaDetector cloud run failed with status code: {response.status_code}")
    # TODO: Investigate pros/cons of making these db operations an atomic transaction within django

    # For each detected bounding box, create a corresponding annotation object
    # Confidence for bounding box & category are the same for MegaDetector
    for i, detection in enumerate(result["detections"]):
        # Create a new annotation object
        bounding_box, created = BoundingBox.objects.get_or_create(
            image=image,
            confidence=detection["conf"],
            x=detection["bbox"][0],
            y=detection["bbox"][1],
            w=detection["bbox"][2],
            h=detection["bbox"][3],
            created_by=annotator,
            confidence_threshold=bot.threshold,
        )
        if created:
            logging.info(
                f"""Successfully created bounding box for object #{i+1} - {detection["category"]} (confidence - {detection["conf"]})"""
            )
        else:
            logging.info("Bounding box already exists. Successfully retrieved.")
        # Next, create a category annotation for it
        category, _ = Category.objects.get_or_create(
            bounding_box=bounding_box,
            name=MEGADETECTOR_LABEL_MAP[detection["category"]],
            created_by=annotator,
            confidence=detection["conf"],
        )

    # Set bbox-related pre-computed flags
    image.has_bbox_above_confidence_threshold = has_bbox_above_confidence_threshold(image)
    image.has_uncertain_bbox = image.boundingbox_set.filter(validity="UNCERTAIN").exists()
    image.save()

    logging.info("All bounding boxes created successfully.")


# Function to process an image
def process_image(image: Image, dbx=None):
    """Function to process an image and create relevant metadata"""
    if dbx is None:
        dbx = create_dropbox_client()

    # First, add a thumbnail to the image object if it doesn't already exist
    if not image.thumbnail_gcloud_path:
        add_thumbnail(image, dbx)

    if image.thumbnail_gcloud_path:
        try:
            # Use SpeciesNet for combined detection and classification
            image_url = f"""https://storage.googleapis.com/{settings.GS_BUCKET_NAME}/media/{image.thumbnail_gcloud_path}"""
            num_detections, species_detections = run_speciesnet_inference(image, image_url)

            # Store species detections
            image.species_ai_detections = species_detections

            image.processed = True
            image.use_precomputed_flags = True
            image.has_cats = "Puma" in image.species_ai_detections or "Bobcat" in image.species_ai_detections
            image.save()
        except Exception as e:
            logging.error(f"Error processing image with SpeciesNet: {e}")
    else:
        logging.error("Thumbnail for image doesn't exist. Skipping..")

    # Return the status of the image processing
    return image.processed
