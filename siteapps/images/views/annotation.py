import ast
import datetime
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import connections
from django.db.models import (BooleanField, Case, CharField, Count, Exists, F,
                              OuterRef, Q, Subquery, Value, When)
from django.http.response import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView
from django.views.generic.base import TemplateView, View
from images.forms import AnnotationForm
from images.models import (Activity, ActivityType, AnnotationCounter,
                           Annotator, BoundingBox, Category, Image, ImageQueue,
                           Species, SpeciesName, SpeciesSubgroup)
from images.models.custom_fields import get_filter_params
from images.processors import (has_bbox_above_confidence_threshold,
                               process_activity_annotations,
                               process_species_annotations,
                               run_model_inference)
from PIL import Image as PILImage

# TODO: There might be some duplicate constants between here and the settings. Should probably move these to the base settings file.
MAX_VOTES_PER_IMAGE = 2
VOTE_THRESHOLD = 1

CATEGORY_ANIMAL = "animal"
CATEGORY_HUMAN = "human"
CUSTOM_PREFIX = "Custom"
SPECIES_QUEUE_NAME = "AnnotateSpeciesQueue"
ACTIVITY_HUMAN_QUEUE_NAME = "AnnotateHumanBehaviorQueue"
ACTIVITY_ANIMAL_QUEUE_NAME = "AnnotateAnimalActivityQueue"

UNKNOWN_CATEGORY = "unknown"

STAFF_OR_EXPERT_CHECK = Q(human__is_staff=True) | Q(human__is_expert=True)
STAFF_OR_EXPERT_VOTE_MULTIPLIER = 2


class BboxAnnotationInfo:
    def __init__(self, id, categories, species, activities):
        self.id = id
        self.categories = categories
        self.species = species
        self.activities = activities


def get_pil_image(image):
    """
    Retrieves the thumbnail of an image.

    Arguments
    ---
        - image (models.Image): The image object to retrieve the thumbnail from.

    Returns
    ---
        - PIL.Image: The image thumbnail data as a PIL image object.
    """
    image_file_path = f"{settings.MEDIA_URL}{image.thumbnail_gcloud_path}"
    response = requests.get(image_file_path)

    pillow_image = None

    if response.status_code == 200:
        # Get the image data
        pillow_image = PILImage.open(BytesIO(response.content)).convert("RGB")

    return pillow_image


def calculate_image_luma(image, bboxes):
    """
    Calculates the percent adjustment needed to brighten the image's subjects to the target luma value (set to 13).

    Arguments
    ---
        - image (images.models.Image): An image object to get the image data from.
        - bboxes (images.models.BoundingBox): The image's bounding box objects to extract coordinates from. Only pixels enclosed by these boxes are used in the calculations.

    Returns
    ---
        - adjustment_percentage (int): The percent increase needed to achieve the optimal brightness, expressed as a whole number (ex. 54 -> 54%).
    """
    TARGET_LUMA = 13

    # Get the image data
    pillow_image = get_pil_image(image)

    if pillow_image:
        width, height = pillow_image.size
        width = round(width * 0.2)
        height = round(height * 0.2)

        pillow_image = pillow_image.resize((width, height))

        pixel_data = []

        # Grab the pixels enclosed by bounding boxes
        for bbox in bboxes:
            x = bbox.x * width
            y = bbox.y * height
            w = x + (bbox.w * width)
            h = y + (bbox.h * height)

            bbox_region = (x, y, w, h)
            cropped_image = pillow_image.crop(bbox_region)
            region_pixel_data = list(cropped_image.getdata())

            pixel_data += region_pixel_data

        if len(pixel_data) == 0:
            return 100

        # Gamma correction
        def apply_gamma_correction(y_value, gamma=2.2):
            corrected_y = int(y_value ** (1 / gamma))

            return corrected_y

        # Calculate luma
        y_values = [(0.257 * r) + (0.504 * g) + (0.098 * b) for (r, g, b) in pixel_data]
        gamma_corrected_y_values = [apply_gamma_correction(y) for y in y_values]

        average_gamma_corrected_y_value = sum(gamma_corrected_y_values) / len(gamma_corrected_y_values)

        adjustment_percentage = round((TARGET_LUMA / average_gamma_corrected_y_value) * 100 - 100)
        adjustment_percentage = max(100, adjustment_percentage)

        return adjustment_percentage


# Get the users annotation counts to increment
def get_or_set_annotation_count(request, queue_name, annotator, annotation_num=0):
    """
    Increments a user's cached annotation count, or calculates and caches the count if it doesn't exist.

    Arguments
    ---
        - request (HttpRequest): The request object to save the annotation count in session storage. Forwarded from the calling view.
        - queue_name (string): One of the predefined constant values used to identify the pipeline the user annotated in. (ex. SPECIES_QUEUE_NAME).
        - annotator (images.models.Annotator): The annotator object used to identify the user annotating.
        - annotation_num (int): The number of annotations made, including tags from multiple/batch tagging.

    Returns
    ---
        - count (int): The number of annotations added to the user's annotation count.
    """

    user_annotations_q_filter = (
        Q(created_by__in=[annotator]) | Q(accepted_by__in=[annotator]) | Q(rejected_by__in=[annotator])
    )

    if SPECIES_QUEUE_NAME in queue_name:
        count = request.session.get("user_species_annotation_count")

        if count is None:
            count = Species.objects.filter(user_annotations_q_filter).count()

        count += annotation_num
        request.session["user_species_annotation_count"] = count

        annotator.total_species_annotations = count
        annotator.save()

    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        count = request.session.get("user_activity_annotation_count")

        if count is None:
            count = Activity.objects.filter(user_annotations_q_filter).count()

        count += annotation_num
        request.session["user_activity_annotation_count"] = count

        annotator.total_activity_annotations = count
        annotator.save()
    else:
        return None

    return count


# Filter criteria for an image to appear in the Species pipeline
def species_pipeline_query(images, annotator, staff_review=False):
    """
    Filters and reorders a set of images based on Species pipeline eligibility.
    - Image must not be checked or skipped by the current annotator.
    - Image has at least one bounding box tagged by MegaDetector above the predetermined threshold.
    - Image has at least 1 uncertain bounding box OR is species incomplete.
    - Image has been preprocessed.

    Arguments
    ---
        images (QuerySet<images.models.Image>): The queryset of images to filter down/order on.
        annotator (images.models.Annotator): The annotator object, used to filter out images they've already been skipped/voted on.

    Returns:
        images (QuerySet<images.models.Image>): The filtered and ordered queryset of images.
    """
    # Only queried when there's no precomputed queues available
    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator]),
        # Image has at least one bounding box tagged by MegaDetector above the predetermined threshold
        Q(has_bbox_above_confidence_threshold=True),
        # Image has at least 1 uncertain bounding box
        Q(has_uncertain_bbox=True)
        # OR is species incomplete, excluding images with only people/vehicles if category's been confirmed
        | (
            ~Q(has_humans=True, has_animals=False)
            & ~Q(has_vehicles=True, has_animals=False)
            & Q(category_pipeline_complete=True, species_pipeline_complete=False)
        ),
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
        upload__deleted=False,
    ).order_by("-upload__priority", "-has_cats", "upload__camera_station", "trigger_timestamp")

    if not staff_review:
        images = images.filter(staff_review_needed=False)

    return images


# Filter criteria for an image to appear in the Activity pipelines
def activity_pipeline_query(images, annotator, activity_category):
    """
    Filters and reorders a set of images based on Activity pipeline eligibility.
    - Image must not be checked or skipped by the current annotator.
    - Image hasn't completed the Activity Pipeline.
    - Image has been preprocessed.

    Arguments
    ---
        images (QuerySet<images.models.Image>): The queryset of images to filter down/order on.
        annotator (images.models.Annotator): The annotator object, used to filter out images they've already been skipped/voted on.

    Returns
    ---
        images (QuerySet<images.models.Image>):
            The filtered and ordered queryset of images.
    """
    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(activity_checked_by__in=[annotator]) & ~Q(activity_skipped_by__in=[annotator]),
        # Image hasn't completed the Activity Pipeline
        activity_pipeline_complete=False,
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
        staff_review_needed=False,
        upload__deleted=False,
    )

    # Filter for animals or humans based on the category passed into the view
    if activity_category == CATEGORY_HUMAN:
        images = images.filter(has_humans=True)
    else:
        images = images.filter(has_wild_animals=True)

    images = images.order_by("-upload__priority", "upload__camera_station", "trigger_timestamp")

    return images


def gather_queue_images(self, queue, queue_name, queue_key, annotator, activity_category, staff_review):
    """
    Gets a new queue of images based on criteria, and caches the results in Datastore.
    This is the legacy queue system and is only called when the precomputed queues run out.

    Arguments
    ---
        - self (django.views.View): The self variable of the view to extract the request data from.
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore.
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - queue_key (string): The dictionary key name to cache the results in Datastore.
        - annotator (images.models.Annotator): The annotator object, used for filtering and identifying objects.
        - activity_category (string): One of the predefined constant values used to distinguish
            between either the human or animal activity pipeline (ex. CATEGORY_HUMAN).
            None if not annotating Activity.
        - staff_review (boolean): Whether annotator is looking at staff review images only or not.

    Returns
    ---
        - queue (google.cloud.datastore.entity.Entity): The newly assigned list of images assigned to the queue.
        - image_id (String): The id of the first image in the queue, or None if it doesn't exist.
    """

    # Get images based on the following set of filters
    images = Image.objects.filter(**self.filterset)

    # Filter using specified pipeline criteria
    if SPECIES_QUEUE_NAME in queue_name:
        images = species_pipeline_query(images=images, annotator=annotator, staff_review=staff_review)
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        images = activity_pipeline_query(images=images, annotator=annotator, activity_category=activity_category)
    else:
        logging.error(f"Invalid queue name provided to query function: {queue_name}")

    # Filter out images with possibly no species AI detections or unidentifiable
    # i.e. potentially erroneous boxes from MegaDetector, or "harder" images to annotate are excluded, so the "easy" ones remain

    images_with_detections = images.exclude(species_ai_detections__in=["[]", "['Unknown']"])

    # Exclude non-animals if annotator's option is active
    if annotator.prioritize_tagging_animals and annotator.prioritize_tagging_animals > timezone.now():
        images_with_detections = images_with_detections.exclude(
            Q(species_ai_detections__icontains="Human") | Q(species_ai_detections__icontains="Vehicle")
        )

    if images_with_detections.exists():
        images = images_with_detections

    # If still no images, just use the original queryset (i.e. only "hard" images remain to be annotated)

    # Get the image stack based on stack size
    images = images[: settings.ANNOTATION_QUEUE_SIZE]

    # Get the image ids & convert to string
    image_ids = []

    # Deduplicate, in case a main image is also a burst image
    def add_id_if_unique(image_id):
        if image_id not in image_ids:
            image_ids.append(image_id)

    for image in images:
        image_id = str(image.id)
        add_id_if_unique(image_id)

        # Append the burst images as well
        if image.trigger_timestamp is not None:
            burst_images = Image.objects.filter(
                ~Q(id=image.id),
                upload=image.upload,
                trigger_timestamp__gt=image.trigger_timestamp - datetime.timedelta(seconds=3),
                trigger_timestamp__lt=image.trigger_timestamp + datetime.timedelta(seconds=3),
            )

            # Make sure the burst image is pipeline eligible
            if SPECIES_QUEUE_NAME in queue_name:
                eligible_burst_image_ids = species_pipeline_query(burst_images, annotator=annotator).values_list(
                    "id", flat=True
                )
            elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
                eligible_burst_image_ids = activity_pipeline_query(
                    burst_images, annotator=annotator, activity_category=activity_category
                ).values_list("id", flat=True)

            # Add burst images to queue, after the main image
            for burst_image_id in eligible_burst_image_ids:
                add_id_if_unique(str(burst_image_id))

    # Create a queue entity with image ids, user id, timestamp and index
    payload = {
        "user": str(self.request.user.id),
        "name": self.request.user.name,
        "images": image_ids,
        "expires_at": (
            datetime.datetime.now() + datetime.timedelta(minutes=settings.ANNOTATION_EXPIRATION_MINS)
        ).isoformat(),
        "index": 0,
    }
    # Upload to datastore
    # If queue is a new entity, create a new key
    if not queue:
        queue = settings.DATASTORE_CLIENT.entity(key=queue_key)
    # Save the queue to the datastore
    queue.update(payload)
    settings.DATASTORE_CLIENT.put(queue)

    return queue, image_ids[0] if image_ids else None


def get_reannotation_image(self, context):
    """
    Extracts the selected image ID to return to and reannotate if it exists in the context dict.
    After returned, can be used to override the original next queue image so it's displayed instead.

    Arguments
    ---
        - self (django.views.View): The self variable of the view to extract the image ID from session storage, if it exists.
        - context (dict): The calling view's context dict to set the reannotation flag in.

    Returns
    ---
        - return_to_image_id (String): The id of the image the annotator chose to go back to and reannotate, if any.
    """
    # Exists if user is returning to a previous image
    return_to_image_id = self.request.session.pop("return_to_image_id", None)
    context["is_reannotation"] = return_to_image_id is not None

    return return_to_image_id


def get_next_queue_image(self, context, queue):
    """
    Gets the next single image to be annotated from the queue. This is only called if there's no precomputed queue available.

    Arguments
    ---
        - self (django.views.View): The self variable of the view.
        - context (dict): The calling view's context dict.
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore for reading the index and images.
    Returns
    ---
        - image_id (String): The id of the next image to show for annotation.
    """
    return_to_image_id = get_reannotation_image(self, context)

    # If not returning to prev. image,
    # get the next image_id from the existing queue
    return return_to_image_id if return_to_image_id else queue["images"][queue["index"]], return_to_image_id


# Skip images completed or made ineligible by other annotators since the queue was built
def skip_ineligible_images(queue_name, queue, annotator):
    """
    Checks images in a cached Datastore queue, and increments the queue index until an eligible image to annotate is found.
    This is not executed if using a precomputed queue.

    An eligible image to annotate is defined as:
        1) Pipeline incomplete - ex. species not annotated and completed by another annotator after the caching
        2) Pipeline eligible - ex. fulfills "has uncertain bounding boxes" requriement to appear in the species pipeline
        3) Has not been voted on by the current user.

    Arguments
    ---
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore for reading the index and images.

    Returns
    ---
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore.
        - annotator (images.models.Annotator): The annotator object, used to determine user-specific annotation status.
    """
    pipeline_completed = True
    pipeline_eligible = True
    already_voted = False

    eligible_image_stop_event = threading.Event()
    eligible_image_stop_event.clear()

    def recalculate_flags(image_id):
        # Skip these costly calculations when the first eligible image is found
        if eligible_image_stop_event.is_set():
            return

        image = Image.objects.get(id=image_id)

        calculateCategoryAnnotationFlags(image)
        calculateSpeciesAnnotationFlags(image)
        calculateActivityAnnotationFlags(image)
        image.save()

        pipeline_completed, pipeline_eligible, already_voted = get_eligibility(image=image)

        # If eligible image, skip calculating the rest
        if not pipeline_completed and pipeline_eligible and not already_voted and not auto_flag_for_staff(image):
            eligible_image_stop_event.set()

    def calculate_flags_parallel(image_ids):
        with ThreadPoolExecutor(max_workers=10) as executor:

            def on_done(future):
                connections.close_all()

            for image_id in image_ids:
                future = executor.submit(recalculate_flags, image_id)
                future.add_done_callback(on_done)

    # Determine conditions where the image should be skipped or not
    def get_eligibility(image):
        if SPECIES_QUEUE_NAME in queue_name:
            pipeline_completed = image.category_pipeline_complete and image.species_pipeline_complete
            pipeline_eligible = BoundingBox.objects.filter(image=image).exists()
            already_voted = Image.objects.filter(
                Q(species_checked_by__in=[annotator]) | Q(species_skipped_by__in=[annotator]), id=image.id
            ).exists()
        elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
            pipeline_completed = image.activity_pipeline_complete
            pipeline_eligible = image.has_humans or image.has_wild_animals
            already_voted = Image.objects.filter(
                Q(activity_checked_by__in=[annotator]) | Q(activity_skipped_by__in=[annotator]), id=image.id
            ).exists()

        return pipeline_completed, pipeline_eligible, already_voted

    # Check the remaining queue
    if queue["index"] < len(queue["images"]):
        calculate_flags_parallel(queue["images"][queue["index"] : len(queue["images"]) - 1])

    # Skip images based on changes or results of recalculations
    while (pipeline_completed or not pipeline_eligible or already_voted) and queue["index"] < len(queue["images"]):
        image = Image.objects.get(id=queue["images"][queue["index"]])

        pipeline_completed, pipeline_eligible, already_voted = get_eligibility(image=image)

        if pipeline_completed:
            queue["index"] += 1
            logging.info(f"Queue image {image.id} was completed by another annotator. Skipping to next image.")
        elif not pipeline_eligible:
            queue["index"] += 1
            logging.info(f"Queue image {image.id} was made ineligible by another annotator. Skipping to next image.")
        elif already_voted:
            queue["index"] += 1
            logging.info(f"User already voted on queue image {image.id}. Skipping to next image.")
        elif auto_flag_for_staff(image):
            queue["index"] += 1
            logging.info(
                f"Queue image {image.id} skipped by many annotators. Flagging for staff and skipping to next image."
            )

    # This doesn't work during a unit test. Added an except to handle that.
    try:
        settings.DATASTORE_CLIENT.put(queue)
    except Exception:
        logging.error(
            "Failed to put datastore queue update. A unit test may have been run on skip_eligible_images(). If so, you may disregard this error."
        )

    return image


def get_annotation_history(context, queue, queue_name, annotator, precomputed_queue=None):
    """
    Retrieves information on the last few images an annotator skipped or edited, and save it in the provided context dict.

    Arguments
    ---
        - context (dict): The calling view's context dict to save the history images to.
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore to check for previous images.
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - annotator (images.models.Annotator): The annotator object, used for filtering user-specific history.
        - precomputed_queue (images.models.ImageQueue): A precomputed queue object to check in place of a normal queue, if it exists.

    Returns
    ---
        - None: No return value, but sets the history images in the provided view context.
    """
    HISTORY_LENGTH = 10

    if precomputed_queue:
        image_history = precomputed_queue.images.all()
    else:
        image_history = Image.objects.filter(id__in=queue["images"])
    context["previous_annotations"] = []

    if SPECIES_QUEUE_NAME in queue_name:
        image_history = image_history.filter(
            Q(species_checked_by__in=[annotator]) | Q(species_skipped_by__in=[annotator])
        )
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        image_history = image_history.filter(
            Q(activity_checked_by__in=[annotator]) | Q(activity_skipped_by__in=[annotator])
        )

    context["previous_queue_images"] = image_history.order_by("-modified")[:HISTORY_LENGTH]

    for image in context["previous_queue_images"]:
        if SPECIES_QUEUE_NAME in queue_name:
            previous_annotations = Species.objects.filter(
                Q(created_by=annotator) | Q(accepted_by__in=[annotator]), bounding_box__image=image
            ).values("name__name")
        elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
            previous_annotations = Activity.objects.filter(
                Q(created_by=annotator) | Q(accepted_by__in=[annotator]), bounding_box__image=image
            ).values("name__name")
        else:
            pass

        if previous_annotations.count() == 0:
            context["previous_annotations"].append("None")
        else:
            context["previous_annotations"].append(
                ", ".join(anno for anno in set(list(annotation.values())[0] for annotation in previous_annotations))
            )

    context["previous_annotation_info"] = zip(context["previous_queue_images"], context["previous_annotations"])


def get_burst_images(context, queue, queue_name, annotator, precomputed_queue=None, current_queue_image=None):
    """
    Get images closely within the same time of the currently annotated image.

    Arguments
    ---
        - context (dict): The calling view's context dict to save the burst images to.
        - queue (google.cloud.datastore.entity.Entity): The retrieved data object from the Datastore to check images from.
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - annotator (images.models.Annotator): The annotator object, used for filtering out already checked images by the annotator.
        - precomputed_queue (images.models.ImageQueue): A precomputed queue object to check in place of a normal queue, if it exists.
        - current_queue_image (images.models.Image): If precompute queue exists, this is used to determine the timestamp range to check for burst images around.

    Returns
    ---
        - None: No return value, but sets the burst images in the provided view context.
    """

    BURST_TIME_THRESHOLD = 120

    images = []

    if precomputed_queue:
        image_ids = (
            precomputed_queue.images.filter(trigger_timestamp__gt=current_queue_image.trigger_timestamp)
            .order_by("trigger_timestamp")
            .values_list("id", flat=True)
        )
        prev_timestamp = current_queue_image.trigger_timestamp
    else:
        image_ids = queue["images"][queue["index"] + 1 :]
        prev_timestamp = Image.objects.get(id=queue["images"][queue["index"]]).trigger_timestamp

    # Check only the next images in queue
    for image_id in image_ids:

        # Make sure the batch images haven't already been voted/completed
        try:
            if SPECIES_QUEUE_NAME in queue_name:
                image = Image.objects.get(~Q(species_checked_by__in=[annotator]), id=image_id)
            elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
                image = Image.objects.get(~Q(activity_checked_by__in=[annotator]), id=image_id)
        except Exception:
            continue

        # Sometimes one of these timestamps don't exist, handle error
        try:
            time_diff = image.trigger_timestamp - prev_timestamp
        except Exception:
            break

        # Check for burst images after, and a bit before timestamp as well
        within_time_check = -3 < time_diff.total_seconds() < BURST_TIME_THRESHOLD

        # If the times are close enough, consider it as potentially part of a burst
        if within_time_check:
            images.append(image)
        else:
            break

    context["images_w_boxes"] = [
        [image_obj, BoundingBox.objects.filter(image=image_obj, validity__in=["VALID", "UNCERTAIN"])]
        for image_obj in images
    ]


# Get pipeline-specific query filters for precomputed queue
def get_pipeline_filters(queue_name, annotator):
    """
    Returns Q filters and keyword args used to determine if any valid images are left to annotate in the queue, and how to retrieve the next image if so.

    Arguments
    ---
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - annotator (images.models.Annotator): The annotator object, for creating the annotator-specific Q filter.

    Returns
    ---
        - annotator_check (django.db.models.Q): A Q filter that filters out images skipped by or checked by the annotator.
        - pipeline_kwarg (dict): A dict of kwargs that when unpacked and applied to a query, filters only images that are not pipeline complete.
                                 If annotator is not staff, also filters out flagged-for-staff images.
    """
    # Try to get an eligible precomputed queue
    pipeline_kwarg = {"upload__deleted": False}
    if SPECIES_QUEUE_NAME in queue_name:
        annotator_check = ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator])
        pipeline_kwarg["species_pipeline_complete"] = False

    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        annotator_check = ~Q(activity_checked_by__in=[annotator]) & ~Q(activity_skipped_by__in=[annotator])
        pipeline_kwarg["activity_pipeline_complete"] = False

    # Exclude human/vehicles if annotator prioritized animals
    if annotator.prioritize_tagging_animals and annotator.prioritize_tagging_animals > timezone.now():
        exclusion_condition = Q(species_ai_detections=None)
        for category in ["Human", "Vehicle"]:
            exclusion_condition |= Q(species_ai_detections__icontains=category)
    else:
        exclusion_condition = Q()

    return annotator_check, pipeline_kwarg, exclusion_condition


# Try to get a valid precomputed queue
def get_precomputed_queue(queue_name, annotator, searched):
    """
    Attempts to find a precomputed queue with valid unannotated images assigned to the provided annotator.
    If none are assigned, find a valid precomputed queue and assign it to the annotator.
    If no valid queues exist, return None.

    Arguments
    ---
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - annotator (images.models.Annotator): The annotator object to check for a queue or assign a queue to.

    Returns
    ---
        - precomputed_queue (images.models.ImageQueue): The assigned precomputed queue associated with an annotator. None if doesn't exist or couldn't assign.
    """
    annotator_check, pipeline_kwarg, exclusion_condition = get_pipeline_filters(queue_name, annotator)

    # Use the pipeline_kwarg in the query
    q_condition = Q(annotator_check) & Q(has_bbox_above_confidence_threshold=True) & Q(staff_review_needed=False)
    queue_condition = Exists(
        Image.objects.filter(
            q_condition,
            Q(queue=OuterRef("pk")),
            **pipeline_kwarg,
        ).exclude(exclusion_condition)
    )

    # If queue is from searching images, include all imgs regardless of eligibility
    precomputed_queue = ImageQueue.objects.filter(assigned_to=annotator)

    if searched:
        return precomputed_queue.first()
    else:
        precomputed_queue = ImageQueue.objects.annotate(has_eligible_image=queue_condition).filter(
            assigned_to=annotator,
            has_eligible_image=True,
        )

    precomputed_queue = precomputed_queue.first()

    if (
        precomputed_queue
        and precomputed_queue.images.filter(
            q_condition, trigger_timestamp__gte=precomputed_queue.partition, **pipeline_kwarg
        )
        .exclude(exclusion_condition)
        .exists()
    ):
        logging.info("Got image from assigned precomputed queue.")
    else:
        logging.info("No assigned precomputed queue. Attempting to assign...")
        try:
            # Mark as checked by annotator so they don't get the same one
            checked_queues = ImageQueue.objects.filter(assigned_to=annotator)
            for queue in checked_queues:
                queue.checked_by.add(annotator)
                queue.assigned_to = None
                queue.save()

            # Get a new queue
            precomputed_queue = (
                ImageQueue.objects.annotate(has_eligible_image=queue_condition)
                .filter(
                    Q(modified__lte=timezone.now() - datetime.timedelta(hours=1)) | Q(assigned_to=None),
                    Q(has_eligible_image=True),
                    ~Q(checked_by__in=[annotator]),
                )
                .first()
            )
            # Reset the partition for new assignment
            precomputed_queue.partition = datetime.datetime.min
            precomputed_queue.assigned_to = annotator
            precomputed_queue.save()
            logging.info("Successfully assigned a precomputed queue.")
        except Exception as e:
            precomputed_queue = None
            logging.info("No precomputed queues left to assign. Querying images...")

    return precomputed_queue


def set_widget_data(context, image, species_list):
    # Move the ai detections species to the top of the list
    ai_detections = None
    if image and image.species_ai_detections:
        try:
            # Try to safely evaluate the string as a Python literal
            ai_detections = ast.literal_eval(image.species_ai_detections)
        except Exception as e:
            logging.error(f"Failed to parse species_ai_detections for image {image.id}: {e}")
            ai_detections = None

    detection_query = Q()
    if ai_detections:
        for det in ai_detections:
            detection_query |= Q(name__icontains=det)
        context["species_list"] = list(species_list.filter(detection_query)) + list(species_list.exclude(detection_query))
    else:
        context["species_list"] = list(species_list)

    # Get the data from the name
    def get_species_button_data(species):
        return {
            "name": species.name,
            "has_vote": species.name in species_tags,
            "ai_detection": image.species_ai_detections is not None and species.name in image.species_ai_detections,
            "selected": False,
        }

    species_tags = []

    for bbox in context["bounding_boxes"]:
        species_tags += Species.objects.filter(bounding_box=bbox).values_list("name__name", flat=True)

    context["widget_data"] = {
        "person": {
            "open": False,
            "data": {
                None: {
                    "items": [
                        get_species_button_data(species) for species in species_list.filter(species_group="HUMAN")
                    ]
                }
            },
        },
        "animal": {"open": False, "data": {}},
        "vehicle": {
            "open": False,
            "data": {
                None: {
                    "items": [
                        get_species_button_data(species) for species in species_list.filter(species_group="VEHICLE")
                    ]
                }
            },
        },
    }

    species_subgroups = [None] + list(SpeciesSubgroup.objects.all())

    animal_list = species_list.filter(Q(species_group="WILD") | Q(species_group="DOMESTIC"))
    animal_widget = context["widget_data"]["animal"]

    for subgroup in species_subgroups:
        sub_species = list(animal_list.filter(subgroup=subgroup))
        group_species = [get_species_button_data(species) for species in sub_species]

        # Has an ai detection or recent tag, tab/accordion open by default
        is_open = any(species["ai_detection"] for species in group_species)

        if len(group_species) > 0:
            animal_widget["data"][subgroup.name if subgroup else None] = {"open": is_open, "items": group_species}
        if is_open:
            # The tab should be selected too
            animal_widget["open"] = True

    # Default open other tabs too
    if not animal_widget["open"]:
        human_list = list(species_list.filter(Q(species_group="HUMAN")))
        context["widget_data"]["person"]["open"] = ai_detections is not None and any(category.name in ai_detections for category in human_list)

        if not context["widget_data"]["person"]["open"]:
            vehicle_list = list(species_list.filter(Q(species_group="VEHICLE")))
            context["widget_data"]["vehicle"]["open"] = ai_detections is not None and any(category.name in ai_detections for category in vehicle_list)

            if not context["widget_data"]["vehicle"]["open"]:
                animal_widget["open"] = True

    context["widget_data"] = json.dumps(context["widget_data"])


# Retrieves data to pass to the views through context (namely queue images and annotations info).
def populate_view_context(queue_name, context, self, activity_category=None, staff_review=False, searched=False):

    """
    Sets data in view context to access from the annotation view templates,
    including the image data, bounding boxes, species suggestions, and more.

    Arguments
    ---
        - queue_name (string): One of the predefined constant values used to identify the pipeline. (ex. SPECIES_QUEUE_NAME).
        - context (dict): The context object passed from the calling view.
        - self (django.views.View): The self variable of the view to extract the request data from.
        - activity_category (string): A constant value of either "human" or "animal," to determine which pipeline to use if annotating Activity,
                                      or None if not annotating Activity.

    """
    # First get the annotator object for the user
    annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

    # Check if we're doing custom annotations
    custom_annotations = self.request.GET.get("custom") == "true"

    # Get the annotation queue cached in the datastore
    queue_name = CUSTOM_PREFIX + queue_name if custom_annotations else queue_name

    queue_key = settings.DATASTORE_CLIENT.key(queue_name, str(self.request.user.id))
    queue = settings.DATASTORE_CLIENT.get(queue_key)

    # Check if we have a valid cached queue of images
    queue_available = (
        queue
        and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
        and queue["index"] < len(queue["images"])
    )

    # Try to get precomputed queue for the pipeline
    annotator_check, pipeline_kwarg, exclusion_condition = get_pipeline_filters(queue_name, annotator)
    precomputed_queue = (
        None
        if (staff_review or custom_annotations)
        else get_precomputed_queue(queue_name=queue_name, annotator=annotator, searched=searched)
    )

    # Image to reannotate to in annotation history, if it exists
    return_to_image_id = None

    # Get eligible images from precomputed queue if it exists
    if precomputed_queue and not custom_annotations:
        return_to_image_id = get_reannotation_image(self, context)

        queue_images = precomputed_queue.images.all()

        if not searched:
            queue_images = queue_images.filter(
                annotator_check, has_bbox_above_confidence_threshold=True, staff_review_needed=False, **pipeline_kwarg
            ).exclude(exclusion_condition)

        partitioned_queue_images = queue_images.filter(trigger_timestamp__gte=precomputed_queue.partition)

        image_id = return_to_image_id if return_to_image_id else partitioned_queue_images.first().id

        # View all images in the queue
        context["grid_images_w_boxes"] = [
            [image_obj, BoundingBox.objects.filter(image=image_obj, validity__in=["VALID", "UNCERTAIN"])]
            for image_obj in queue_images.exclude(exclusion_condition, id=image_id)
        ]

    # Use old queue system as a fallback method if the precomputed queues run out
    elif queue_available:
        image_id, return_to_image_id = get_next_queue_image(self=self, context=context, queue=queue)
    else:
        logging.info("Gathering new queue of images...")
        # Serve the first image
        queue, image_id = gather_queue_images(
            self=self,
            queue=queue,
            queue_name=queue_name,
            queue_key=queue_key,
            annotator=annotator,
            activity_category=activity_category,
            staff_review=staff_review,
        )

    # If there is a valid image, add bounding box information
    if image_id:
        image = Image.objects.get(id=image_id)

        if return_to_image_id is None and not precomputed_queue and not staff_review:
            skip_result = skip_ineligible_images(queue_name=queue_name, queue=queue, annotator=annotator)
            image = skip_result if skip_result else image

        context["image"] = image
        context["social_media_worthy"] = image.social_media_worthy
        context["staff_review_needed"] = image.staff_review_needed
        context["bounding_boxes"] = get_valid_or_uncertain_bboxes(image=image)
        context["queue_index"] = queue["index"] if queue else None
        context["queue_length"] = len(queue["images"]) if queue else None
        context["searched"] = searched

        # Calculate image luma
        context["luma_adjustment"] = calculate_image_luma(image, context["bounding_boxes"])

        # Get previously annotated images and their information
        if precomputed_queue:
            get_annotation_history(context, queue, queue_name, annotator, precomputed_queue=precomputed_queue)
        else:
            get_annotation_history(context, queue, queue_name, annotator)
        # Gather surrounding context images
        if image.context_image_gcloud_paths:
            try:
                from ast import literal_eval

                context["context_images"] = literal_eval(str(image.context_image_gcloud_paths))
            except Exception:
                logging.info(f"Failed to get context images for image {image_id}.")

        # Gather all annotations for bounding boxes to display in admin view.
        get_all_annotations(image=image, context=context)

        # Get user annotation count
        context["user_annotation_count"] = get_or_set_annotation_count(
            request=self.request, queue_name=queue_name, annotator=annotator
        )

        # Get burst images for multi-image tagging
        if precomputed_queue:
            get_burst_images(
                context=context,
                queue=queue,
                queue_name=queue_name,
                annotator=annotator,
                precomputed_queue=precomputed_queue,
                current_queue_image=image,
            )
        elif queue["index"] < context["queue_length"]:
            get_burst_images(context=context, queue=queue, queue_name=queue_name, annotator=annotator)

    else:
        image = None
        context["image"] = None
        context["bounding_boxes"] = []

    # Run AI species detection, or get saved results
    if SPECIES_QUEUE_NAME in queue_name and context["image"]:
        # Current image
        species_inference_current(image, context)

    # Separate species into groups for the widget to render
    species_list = SpeciesName.objects.filter(~Q(name=UNKNOWN_CATEGORY), active=True)

    set_widget_data(context, image, species_list)

    context["activity_list"] = ActivityType.objects.filter(category=activity_category)
    context["custom_annotations"] = custom_annotations

    if SPECIES_QUEUE_NAME in queue_name:
        context["pipeline"] = "species"
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name:
        context["pipeline"] = "animal activity"
    elif ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        context["pipeline"] = "human activity"


# Detect species with AI in the current image, or get previously cached results
def species_inference_current(image, context):
    """
    Checks if species inference has already been run and saved on the image.
    If not, calls the Cloud Function and saves the list of detected species.

    NOTE: All images after Feb 1 2024 should run species inference immediately on upload,
          so there should always be cached inferences.

    Arguments
    ---
        - image (images.models.Image): The current image being annotated.
        - context (dict): The context object passed from the calling view, to load the list of detected species into.

    """
    from ast import literal_eval

    # Check if current image is already inferred for species
    if image.species_ai_detections is not None:
        logging.info("Cached species detections found.")
    elif not settings.DEBUG:
        logging.info("No cached species detections. Running inference...")
        image.species_ai_detections = run_model_inference(image, species=True)
        image.save()

    # Convert the string representation to an actual list
    try:
        context["species_detections"] = literal_eval(str(image.species_ai_detections))
    except Exception as e:
        logging.error(f"Error reading species detections: {e}")


def auto_flag_for_staff(image):
    """
    Checks the current image to see how many annotators have skipped.
    If that number is above AUTO_REVIEW_FLAG_THRESHOLD, flag the image for staff review,
    thereby removing it from showing to regular users.

    Arguments
    ---
        - image (images.models.Image): The current image being annotated.
    """
    AUTO_REVIEW_FLAG_THRESHOLD = 2

    if (
        image.bbox_skipped_by.count() > AUTO_REVIEW_FLAG_THRESHOLD
        or image.species_skipped_by.count() > AUTO_REVIEW_FLAG_THRESHOLD
        or image.activity_skipped_by.count() > AUTO_REVIEW_FLAG_THRESHOLD
    ):
        image.staff_review_needed = True
        image.save()
        logging.info(f"Image {image.id} autoflagged for staff review due to many annotators skipping.")

        return True
    else:
        return False


# Filter out the rejected bboxes
def get_valid_or_uncertain_bboxes(image):
    bounding_boxes = BoundingBox.objects.filter(image__id=image.id)
    bounding_box_values = bounding_boxes.values()

    zipped_querysets = list(zip(bounding_boxes, bounding_box_values))
    annotate(zipped_querysets)

    return [bbox_obj for bbox_obj, bbox_values in zipped_querysets if bbox_values.get("status") != "INVALID"]


def get_all_annotations(image, context):
    """
    Extracts all annotation data in the current image,
    and saves it to the view context to be accessed from the interface.

    Arguments
    ---
        - image (images.models.Image): The current image being annotated.
        - context (dict): The context object passed from the calling view, to save the annotation data into.
    """
    try:
        bboxes = BoundingBox.objects.filter(image=image)
    except (ObjectDoesNotExist, IndexError):
        bboxes = []

    infoList = []

    for bbox in bboxes:
        categories = Category.objects.filter(bounding_box=bbox)
        species = Species.objects.filter(bounding_box=bbox)
        activities = Activity.objects.filter(bounding_box=bbox)

        infoList.append(BboxAnnotationInfo(bbox.id, categories, species, activities))

    context["bbox_all_annotations"] = infoList


class CustomAnnotationView(LoginRequiredMixin, FormView, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/custom_annotation.html"
    form_class = AnnotationForm

    def post(self, request, *args, **kwargs):
        form = AnnotationForm(request.POST)

        if form.is_valid():
            start_date = form.cleaned_data["start_date"]
            end_date = form.cleaned_data["end_date"]
            macrosites = form.cleaned_data["macrosites"]
            macrosite_name = macrosites.name
            camera_stations = form.cleaned_data["camera_stations"]
            annotation_choices = form.cleaned_data["annotation_choices"]
            if camera_stations:
                camera_id = camera_stations.station_id
            else:
                camera_id = "None"

            if annotation_choices == "species":
                url = (
                    reverse("images:annotate_species")
                    + f"?custom=true&start_date={start_date}&end_date={end_date}&macrosite_name={macrosite_name}&camera_id={camera_id}"
                )
                queue_name = CUSTOM_PREFIX + SPECIES_QUEUE_NAME
            elif annotation_choices == "human" or annotation_choices == "animal":
                url = reverse("images:annotate_activity", kwargs={"category": annotation_choices})
                url += f"?custom=true&start_date={start_date}&end_date={end_date}&macrosite_name={macrosite_name}&camera_id={camera_id}"
                if annotation_choices == "human":
                    queue_name = CUSTOM_PREFIX + ACTIVITY_HUMAN_QUEUE_NAME
                else:
                    queue_name = CUSTOM_PREFIX + ACTIVITY_ANIMAL_QUEUE_NAME
            else:
                logging.error(f"Invalid selection for custom annotations: {annotation_choices}.")

            # Clear the queue since we're starting a new Custom Annotation set
            queue_key = settings.DATASTORE_CLIENT.key(queue_name, str(self.request.user.id))
            settings.DATASTORE_CLIENT.delete(queue_key)

            return redirect(url)


# Sets filterset for custom annotations
def set_view_filterset(self, staff_review=False):
    start_date = self.request.GET.get("start_date")
    end_date = self.request.GET.get("end_date")
    camera_id = None if self.request.GET.get("camera_id") == "None" else self.request.GET.get("camera_id")
    macrosite_name = self.request.GET.get("macrosite_name")

    self.filterset = get_filter_params(start_date, end_date, macrosite_name, camera_id, staff_review)


class AnnotateSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/species.html"

    def get(self, request, *args, **kwargs):
        set_view_filterset(self, staff_review=kwargs.get("staff_review", False))

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        populate_view_context(
            SPECIES_QUEUE_NAME,
            context,
            self,
            staff_review=kwargs.get("staff_review", False),
            searched=kwargs.get("searched", False) and self.request.user.is_staff,
        )

        return context


class AnnotateActivityView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/activity.html"

    def get(self, request, *args, **kwargs):
        set_view_filterset(self)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        activity_category = self.request.GET.get("annotation_choice") or self.kwargs["category"]

        # Get the annotation queue based on the selections
        if activity_category == CATEGORY_HUMAN:
            queue_name = ACTIVITY_HUMAN_QUEUE_NAME
        else:
            queue_name = ACTIVITY_ANIMAL_QUEUE_NAME

        populate_view_context(queue_name, context, self, activity_category)

        context["activity_category"] = activity_category

        return context


# Handles annotation processing for each queue type
def annotation_processor(queue_name, annotation_type, request):
    """
    Performs a variety of actions upon a user saving the image after annotation,
    including updating the image data, creating/updating annotation objects, and recalculating pipeline flags.

    Arguments
    ---
        - queue_name (string): One of the predefined constant values used to identify the pipeline the user annotated in. (ex. SPECIES_QUEUE_NAME).
        - annotation_type (string): A string value used to identify the pipeline in annotation counter objects.
        - request (HttpRequest): The request object to retrieve the data from the user's annotations.
    """

    # Get the image id
    image_id = request.POST.get("image_id")
    skip = request.POST.get("skip") == "true"

    # Annotator returned to a previous image (i.e. this one)
    is_reannotation = request.POST.get("is_reannotation") == "True"

    # Get bounding box ids that were sent to infer deleted annotations
    initial_bboxes = request.POST.get("initial_bboxes")
    initial_bboxes = json.loads(initial_bboxes) if initial_bboxes else {}

    # Get the annotation payload from the request and convert it to a dict
    annotations = request.POST.get("annotations")
    annotations = json.loads(annotations) if annotations else {}

    # Apply the social media worthy vote
    social_media_worthy_vote = int(request.POST.get("social_media_worthy_vote"))

    # Check if the image was tagged as needing staff review
    staff_review_needed = request.POST.get("staff_review_needed")
    staff_review_needed = bool(staff_review_needed and staff_review_needed == "true")

    # Get images to batch tag
    batch_tag_images = request.POST.get("batch_tag_images")
    batch_tag_images = json.loads(batch_tag_images) if batch_tag_images else []

    # This count is done before making changes to the bboxes, otherwise validity will change
    batch_bbox_count = (
        BoundingBox.objects.filter(image__id__in=batch_tag_images, validity__in=["Valid", "UNCERTAIN"])
        .distinct()
        .count()
    )

    annotation_description = None

    # Process the annotations
    if queue_name == SPECIES_QUEUE_NAME:
        annotation_description = "Species"
        success = process_species_annotations(
            image_id=image_id,
            annotations=annotations,
            initial_bboxes=initial_bboxes,
            user=request.user,
            social_media_worthy_vote=social_media_worthy_vote,
            staff_review_needed=staff_review_needed,
            batch_tag_images=batch_tag_images,
            skip=skip,
        )

    elif queue_name == ACTIVITY_ANIMAL_QUEUE_NAME:
        annotation_description = "Animal activity"
        success = process_activity_annotations(
            image_id=image_id,
            annotations=annotations,
            initial_bboxes=initial_bboxes,
            user=request.user,
            social_media_worthy_vote=social_media_worthy_vote,
            staff_review_needed=staff_review_needed,
            batch_tag_images=batch_tag_images,
            skip=skip,
        )

    elif queue_name == ACTIVITY_HUMAN_QUEUE_NAME:
        annotation_description = "Human activity"
        success = process_activity_annotations(
            image_id=image_id,
            annotations=annotations,
            initial_bboxes=initial_bboxes,
            user=request.user,
            social_media_worthy_vote=social_media_worthy_vote,
            staff_review_needed=staff_review_needed,
            batch_tag_images=batch_tag_images,
            skip=skip,
        )

    else:
        logging.error(f"Invalid queue name provided to annotation processor function: {queue_name}")
        success = False

    if skip:
        logging.info(
            f"{annotation_description} annotations for image '{image_id}' was skipped by user - '{request.user.name}'"
        )

        # Flag image for review if many annotators have skipped
        image = Image.objects.get(id=image_id)
        auto_flag_for_staff(image)

    # If success, update image index in the datastore
    if success:
        # Calculate and set the flags
        image = Image.objects.get(id=image_id)
        category_debug_data = calculateCategoryAnnotationFlags(image)
        species_debug_data = calculateSpeciesAnnotationFlags(image)
        activity_debug_data = calculateActivityAnnotationFlags(image)

        image.save()

        # Check if we're doing custom annotations
        custom_annotations = request.POST.get("custom_annotations", False) == "True"

        # Get the annotation queue cached in the datastore
        if custom_annotations:
            queue_name = CUSTOM_PREFIX + queue_name
        queue = settings.DATASTORE_CLIENT.get(settings.DATASTORE_CLIENT.key(queue_name, str(request.user.id)))

        # Update the index
        if queue:
            queue["index"] += 1 if not is_reannotation else 0

            # Update the datastore
            settings.DATASTORE_CLIENT.put(queue)

        if not skip:
            annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)

            # Unflag if checked by staff
            if annotator.human.is_staff:
                logging.info(f"Image {image.id} checked by staff. Resetting review flag.")
                image.staff_review_needed = False
                image.save()

            # Update the cached annotation count
            annotation_count = len(annotations) + batch_bbox_count
            image_count = 1 + len(batch_tag_images)

            get_or_set_annotation_count(
                request=request,
                queue_name=queue_name,
                annotator=annotator,
                annotation_num=annotation_count,
            )

            # Use an object to track each day, for each annotator, for each pipeline
            today = datetime.datetime.today()

            counter = AnnotationCounter.objects.filter(
                annotator=annotator, annotation_type=annotation_type, created__day=today.day, created__month=today.month
            ).first()

            if counter:
                counter.annotation_count += annotation_count
                counter.image_count += image_count
                counter.save()
            else:
                AnnotationCounter.objects.create(
                    annotator=annotator,
                    annotation_type=annotation_type,
                    annotation_count=annotation_count,
                    image_count=image_count,
                )
    else:
        category_debug_data = None
        species_debug_data = None
        activity_debug_data = None

    return JsonResponse(
        {
            "success": success,
            "category_debug_data": category_debug_data,
            "species_debug_data": species_debug_data,
            "activity_debug_data": activity_debug_data,
        }
    )


class SpeciesAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return annotation_processor(SPECIES_QUEUE_NAME, "species", request)


class ActivityAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # Retrieve the activity category type
        activity_category = request.POST.get("activity_category")

        # Get the associated queue name
        if activity_category == CATEGORY_HUMAN:
            queue_name = ACTIVITY_HUMAN_QUEUE_NAME
        elif activity_category == CATEGORY_ANIMAL:
            queue_name = ACTIVITY_ANIMAL_QUEUE_NAME
        else:
            queue_name = None

        return annotation_processor(queue_name, "activity", request)


class DeleteAnnotationView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        model = request.POST.get("model")
        boxId = request.POST.get("boxId")
        annotationName = request.POST.get("annotationName")

        success = None
        bbox = BoundingBox.objects.get(id=boxId)

        try:
            if model == "category":
                category = Category.objects.get(bounding_box=bbox, name=annotationName)
                category.delete()
                success = True
            elif model == "species":
                species = Species.objects.get(bounding_box=bbox, name__name=annotationName)
                species.delete()
                success = True
            elif model == "activity":
                activity = Activity.objects.get(bounding_box=bbox, name__name=annotationName)
                activity.delete()
                success = True
        except ObjectDoesNotExist:
            success = False
        return JsonResponse({"success": success, "name": annotationName})


class ChangeAnnotationView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        model = request.POST.get("model")
        boxId = request.POST.get("boxId")
        annotationName = request.POST.get("annotationName")
        newAnnotationName = request.POST.get("newAnnotationName")

        success = None
        bbox = BoundingBox.objects.get(id=boxId)

        try:
            if model == "category":
                category = Category.objects.get(bounding_box=bbox, name=annotationName)
                category.name = newAnnotationName
                category.save()
                success = True
            elif model == "species":
                species = Species.objects.get(bounding_box=bbox, name__name=annotationName)
                species.name = SpeciesName.objects.get(name=newAnnotationName)
                species.save()
                success = True
            elif model == "activity":
                activity = Activity.objects.get(bounding_box=bbox, name__name=annotationName)
                activity.name = newAnnotationName
                activity.save()
                success = True
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success, "oldName": annotationName, "newName": newAnnotationName})


"""
Pipeline flag calculations.
"""


def annotate(zipped_querysets):
    """
    Alternative to the ORM .annotate() to calculate object properties, which returns incorrect data due to multiple aggregations.
    Takes a zip object containing a list of annotation objects to reference,
    and its .value() list to append data to.

    Calculates the votes and validity of the given object (BoundingBox or Image),
    and adds that data to the original field values list in the zipped tuples.

    Arguments
    ---
        - zipped_querysets (iterator): An iterator object containing tuples of annotation objects and their respective values list.
    """

    for obj, annotation in zipped_querysets:
        annotation["accepted_count"] = obj.accepted_by.count() + (1 if obj.created_by.type == "human" else 0)
        annotation["rejected_count"] = obj.rejected_by.count()

        annotation["vote_difference"] = annotation.get("accepted_count") - annotation.get("rejected_count")

        annotation["staff_or_expert_votes"] = obj.accepted_by.filter(STAFF_OR_EXPERT_CHECK).count() + (
            1 if (obj.created_by.human and (obj.created_by.human.is_staff or obj.created_by.human.is_expert)) else 0
        )
        annotation["has_staff_or_expert_vote"] = annotation["staff_or_expert_votes"] > 0

        staff_or_expert_rejection_count = obj.rejected_by.filter(STAFF_OR_EXPERT_CHECK).count()
        staff_or_expert_rejection = staff_or_expert_rejection_count > 0

        correlated_obj_rejected = False

        if hasattr(obj, "bounding_box"):
            bbox_obj = BoundingBox.objects.filter(id=obj.bounding_box.id)
            bbox_values = bbox_obj.values()

            zipped_bbox_querysets = list(zip(bbox_obj, bbox_values))
            annotate(zipped_bbox_querysets)

            correlated_obj_rejected = zipped_bbox_querysets[0][1].get("status") == "INVALID"

        if (
            annotation.get("vote_difference") > VOTE_THRESHOLD
            and not staff_or_expert_rejection
            and not correlated_obj_rejected
            # Some annotations have incorrect staff/expert votes,
            # Override acception for every two other staff/experts who concur on rejection
        ) or (
            annotation["staff_or_expert_votes"] > 0
            and staff_or_expert_rejection_count <= annotation["staff_or_expert_votes"]
        ):
            annotation["status"] = "VALID"
        elif (
            annotation.get("vote_difference") < -VOTE_THRESHOLD
            or (0 != staff_or_expert_rejection_count >= (annotation["staff_or_expert_votes"] * 2))
            or correlated_obj_rejected
        ):
            if annotation["has_staff_or_expert_vote"]:
                logging.info(
                    f"Staff/expert accept votes for {type(obj)} {obj.id} was overriden because 2 or more staff/experts rejected it."
                )
            annotation["status"] = "INVALID"
        else:
            annotation["status"] = "UNCERTAIN"


# Category Flag Checks
def calculateCategoryAnnotationFlags(image):
    """
    Determines Category pipeline completion based on a number of criteria, and sets the respective flags in the image.
    Sets flags depending on what type of objects are in the image only if pipeline complete.

    Arguments
    ---
        - image (models.Image): The image object to check, calculate on, and update.
    """
    category_objs = Category.objects.filter(bounding_box__image=image)
    category_annotations = category_objs.values()

    bounding_box_objs = BoundingBox.objects.filter(image=image)
    bounding_box_annotations = bounding_box_objs.values()

    zipped_bbox_querysets = list(zip(bounding_box_objs, bounding_box_annotations))
    annotate(zipped_bbox_querysets)

    zipped_querysets = list(zip(category_objs, category_annotations))
    annotate(zipped_querysets)

    category_has_uncertain_annotation = any(
        category[1].get("status") == "UNCERTAIN" for category in zipped_querysets
    ) or any(bbox[1].get("status") == "UNCERTAIN" for bbox in zipped_bbox_querysets)

    has_staff_or_expert_vote = any(category[1].get("has_staff_or_expert_vote") is True for category in zipped_querysets)

    not_invalid_bbox_count_gt = len(zipped_bbox_querysets) > 0 and any(
        bbox[1].get("status") != "INVALID" for bbox in zipped_bbox_querysets
    )

    # Save bbox validity status
    for bbox in zipped_bbox_querysets:
        bbox[0].validity = bbox[1].get("status")
        bbox[0].save()

    if not category_has_uncertain_annotation and image.processed and not_invalid_bbox_count_gt:
        image.has_humans = category_annotations.filter(name="person").exists()
        image.has_animals = category_annotations.filter(name="animal").exists()
        image.has_vehicles = category_annotations.filter(name="vehicle").exists()

        image.category_pipeline_complete = True
    else:
        # Reset the flags if conditions not met (i.e. retroactively send image back)
        image.category_pipeline_complete = False
        image.has_humans = False
        image.has_animals = False
        image.has_vehicles = False

    category_annotations_info = []
    for category in list(category_annotations):
        category_annotations_info.append(
            {
                "name": category.get("name"),
                "accepted_count": category.get("accepted_count"),
                "rejected_count": category.get("rejected_count"),
                "expert_accepted_count": category.get("staff_or_expert_accepted_count"),
                "expert_rejected_count": category.get("staff_or_expert_rejected_count"),
                "vote_difference": category.get("vote_difference"),
                "status": category.get("status"),
                "has_staff_or_expert_vote": category.get("has_staff_or_expert_vote"),
            }
        )

    for bbox in list(bounding_box_annotations):
        category_annotations_info.append(
            {
                "name": f"BBOX-{bbox.get('id')}",
                "accepted_count": bbox.get("accepted_count"),
                "rejected_count": bbox.get("rejected_count"),
                "expert_accepted_count": bbox.get("staff_or_expert_accepted_count"),
                "expert_rejected_count": bbox.get("staff_or_expert_rejected_count"),
                "vote_difference": bbox.get("vote_difference"),
                "status": bbox.get("status"),
                "has_staff_or_expert_vote": bbox.get("has_staff_or_expert_vote"),
            }
        )

    category_debug_data = {
        "category_annotations": category_annotations_info,
        "flag_checks": {
            "or_checks": {
                "category_has_uncertain": category_has_uncertain_annotation,
                "has_staff_or_expert_vote": has_staff_or_expert_vote,
            },
            "processed": image.processed,
            "bounding_boxes_gte_zero": not_invalid_bbox_count_gt,
        },
        "pipeline_flags": {
            "has_humans": image.has_humans,
            "has_animals": image.has_animals,
            "has_vehicles": image.has_vehicles,
            "category_pipeline_complete": image.category_pipeline_complete,
        },
    }

    return category_debug_data


# Species Flag Checks
def calculateSpeciesAnnotationFlags(image):
    """
    Determines Species pipeline completion based on a number of criteria, and sets the respective flags in the image.
    Sets flags whether wild animals exists in the image only if pipeline complete.

    Arguments
    ---
        - image (models.Image): The image object to check, calculate on, and update.
    """
    species_objs = Species.objects.filter(bounding_box__image__id=image.id)
    species_annotations = species_objs.values()

    zipped_querysets = list(zip(species_objs, species_annotations))
    annotate(zipped_querysets)

    species_has_uncertain_annotation = any(species[1].get("status") == "UNCERTAIN" for species in zipped_querysets)

    species_valid_annotations = [
        species_obj
        for species_obj, species_annotation in zipped_querysets
        if species_annotation.get("status") == "VALID"
    ]

    species_has_valid_annotation = len(species_valid_annotations) > 0

    has_staff_or_expert_vote = any(species[1].get("has_staff_or_expert_vote") is True for species in zipped_querysets)

    annotation_checked_by_gte = image.species_checked_by.all().count() >= MAX_VOTES_PER_IMAGE

    if (
        not species_has_uncertain_annotation
        and species_has_valid_annotation
        and (annotation_checked_by_gte or has_staff_or_expert_vote)
        and image.processed
        and image.category_pipeline_complete
    ):
        image.has_wild_animals = species_annotations.filter(name__species_group="WILD").exists()
        image.has_cats = species_annotations.filter(name__name__in=["Bobcat", "Puma"]).exists()
        image.species_pipeline_complete = True
    else:
        # Reset the flags if conditions not met (i.e. retroactively send image back)
        image.species_pipeline_complete = False
        image.has_wild_animals = False

    # bbox-related precomputed flags
    image.has_bbox_above_confidence_threshold = has_bbox_above_confidence_threshold(image)
    image.has_uncertain_bbox = image.boundingbox_set.filter(validity="UNCERTAIN").exists()

    species_annotations_info = []
    for species in list(species_annotations):
        species_annotations_info.append(
            {
                "name": SpeciesName.objects.get(id=species.get("name_id")).name,
                "accepted_count": species.get("accepted_count"),
                "rejected_count": species.get("rejected_count"),
                "expert_accepted_count": species.get("staff_or_expert_accepted_count"),
                "expert_rejected_count": species.get("staff_or_expert_rejected_count"),
                "vote_difference": species.get("vote_difference"),
                "status": species.get("status"),
                "has_staff_or_expert_vote": species.get("has_staff_or_expert_vote"),
            }
        )

    species_debug_data = {
        "species_annotations": species_annotations_info,
        "flag_checks": {
            "species_has_uncertain": species_has_uncertain_annotation,
            "species_has_valid": species_has_valid_annotation,
            "image_has_animals": image.has_animals,
            "or_checks": {
                "checked_by": annotation_checked_by_gte,
                "has_staff_or_expert_vote": has_staff_or_expert_vote,
            },
            "processed": image.processed,
        },
        "pipeline_flags": {
            "has_wild_animals": image.has_wild_animals,
            "species_pipeline_complete": image.species_pipeline_complete,
        },
    }

    return species_debug_data


# Activity Flag Checks
def calculateActivityAnnotationFlags(image):
    """
    Determines Activity pipeline completion based on a number of criteria, and sets the respective flag in the image.

    Arguments
    ---
        - image (models.Image): The image object to check, calculate on, and update.
    """
    activity_objs = Activity.objects.filter(bounding_box__image__id=image.id)
    activity_annotations = activity_objs.values()

    zipped_querysets = list(zip(activity_objs, activity_annotations))
    annotate(zipped_querysets)

    activity_has_uncertain_annotation = any(activity[1].get("status") == "UNCERTAIN" for activity in zipped_querysets)

    activity_has_valid_annotation = any(activity[1].get("status") == "VALID" for activity in zipped_querysets)

    has_staff_or_expert_vote = any(activity[1].get("has_staff_or_expert_vote") is True for activity in zipped_querysets)

    annotation_checked_by_gte = image.activity_checked_by.all().count() >= MAX_VOTES_PER_IMAGE

    if (
        not activity_has_uncertain_annotation
        and activity_has_valid_annotation
        and image.has_wild_animals
        and (annotation_checked_by_gte or has_staff_or_expert_vote)
        and image.processed
    ):
        image.activity_pipeline_complete = True
    else:
        image.activity_pipeline_complete = False

    activity_annotations_info = []
    for activity in list(activity_annotations):
        activity_annotations_info.append(
            {
                "name": ActivityType.objects.get(id=activity.get("name_id")).name,
                "accepted_count": activity.get("accepted_count"),
                "rejected_count": activity.get("rejected_count"),
                "expert_accepted_count": activity.get("staff_or_expert_accepted_count"),
                "expert_rejected_count": activity.get("staff_or_expert_rejected_count"),
                "vote_difference": activity.get("vote_difference"),
                "status": activity.get("status"),
                "has_staff_or_expert_vote": activity.get("has_staff_or_expert_vote"),
            }
        )

    activity_debug_data = {
        "activity_annotations": activity_annotations_info,
        "flag_checks": {
            "activity_has_uncertain": activity_has_uncertain_annotation,
            "activity_has_valid": activity_has_valid_annotation,
            "image_has_wild_animals": image.has_wild_animals,
            "or_checks": {
                "has_staff_or_expert_vote": has_staff_or_expert_vote,
                "checked_by": annotation_checked_by_gte,
            },
            "processed": image.processed,
        },
        "pipeline_flags": {"activity_pipeline_complete": image.activity_pipeline_complete},
    }

    return activity_debug_data


class SaveRecentTagsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        annotations = request.POST.get("annotations")
        success = True

        try:
            request.session["recent_tags"] = annotations
        except BaseException as e:
            logging.error(f"Error saving recent tags: {e}")
            success = False

        return JsonResponse({"success": success})


class GetRecentTagsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = True

        try:
            recent_tags = self.request.session.get("recent_tags", [])
        except BaseException as e:
            logging.error(f"Error retrieving recent tags: {e}")
            success = False

        return JsonResponse({"success": success, "recent_tags": recent_tags})


class SavePreviousImageToReturnToView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = True

        return_to_image_id = request.POST.get("returnToImageId")

        try:
            request.session["return_to_image_id"] = return_to_image_id
        except Exception as e:
            logging.error(f"Error saving image id to return to: {e}")
            success = False

        return JsonResponse({"success": success})
