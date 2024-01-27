import datetime
import json
import logging
from io import BytesIO

import numpy as np
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import (
    BooleanField,
    Case,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, math
from django.http.response import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import FormView
from django.views.generic.base import TemplateView, View
from images.forms import AnnotationForm
from images.models import (
    Activity,
    ActivityType,
    AnnotationCounter,
    Annotator,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
)
from images.models.custom_fields import get_filter_params
from images.processors import process_activity_annotations, process_species_annotations
from locations.models import CameraStation, MacroSite, MicroSite
from PIL import Image as PILImage

MAX_VOTES_PER_IMAGE = 2
VOTE_THRESHOLD = 1

CATEGORY_ANIMAL = "animal"
CATEGORY_HUMAN = "human"
CUSTOM_PREFIX = "Custom"
SPECIES_QUEUE_NAME = "AnnotateSpeciesQueue"
ACTIVITY_HUMAN_QUEUE_NAME = "AnnotateHumanBehaviorQueue"
ACTIVITY_ANIMAL_QUEUE_NAME = "AnnotateAnimalActivityQueue"

UNANNOTATED_CATEGORY = "unannotated"

STAFF_OR_EXPERT_CHECK = Q(human__is_staff=True) | Q(human__is_expert=True)
STAFF_OR_EXPERT_VOTE_MULTIPLIER = 2


class BboxAnnotationInfo:
    def __init__(self, id, categories, species, activities):
        self.id = id
        self.categories = categories
        self.species = species
        self.activities = activities


def calculate_image_luma(image, bboxes):
    TARGET_LUMA = 13

    image_file_path = f"{settings.MEDIA_URL}{image.thumbnail_gcloud_path}"
    response = requests.get(image_file_path)

    if response.status_code == 200:
        # Get the image data
        pillow_image = PILImage.open(BytesIO(response.content)).convert("RGB")

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


def staff_review_query_filter(images, annotator):
    if "prod" in settings.WSGI_APPLICATION and annotator and annotator.human.is_staff:
        # Show images needing review first
        images = images.order_by("-staff_review_needed")
    else:
        # Image hasn't been marked for staff review
        images = images.filter(staff_review_needed=False)

    return images


# Filter criteria for an image to appear in the Species pipeline
def species_pipeline_query(images, annotator):
    # Auto migrate a small portion of images in case there's no images available
    # Remove this code when all images have had precomputed flags recalculated
    def migrate_images():
        logging.info("Running image flag recalculations in the background...")
        migrate_images = Image.objects.filter(
            Exists(
                BoundingBox.objects.filter(image=OuterRef("pk"), validity=None, image__species_pipeline_complete=False)
            ),
        ).order_by("-upload__priority")[:500]

        def recalc(image):
            category_debug_data = calculateCategoryAnnotationFlags(image)
            species_debug_data = calculateSpeciesAnnotationFlags(image)
            activity_debug_data = calculateActivityAnnotationFlags(image)

            image.save()

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(recalc, image) for image in migrate_images]

    import threading

    thread = threading.Thread(target=migrate_images, args=[])
    thread.name = "migrate-images"
    thread.setDaemon(True)
    thread.start()

    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator]),
        # Image has at least one bounding box tagged by MegaDetector above the predetermined threshold
        Exists(
            BoundingBox.objects.filter(image=OuterRef("pk"))
            .annotate(
                # TODO: This calculation can happen after MegaDetector processing, and we can set a flag.
                confidence_threshold=Case(
                    When(created_by__type="bot", then="created_by__bot__threshold"),
                    default=0.0,
                ),
            )
            .filter(
                ~Q(validity__in=["Invalid", None]),
                confidence__gte=F("confidence_threshold"),
            )
        ),
        # Image has at least 1 uncertain bounding box
        Exists(BoundingBox.objects.filter(image=OuterRef("pk"), validity="Uncertain"))
        # OR is species incomplete, excluding images with only people/vehicles if category's been confirmed
        | (
            ~Q(has_humans=True, has_animals=False)
            & ~Q(has_vehicles=True, has_animals=False)
            & Q(category_pipeline_complete=True, species_pipeline_complete=False)
        ),
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
    ).order_by("-upload__priority", "upload__camera_station", "trigger_timestamp")

    images = staff_review_query_filter(images, annotator)

    return images


# Filter criteria for an image to appear in the Activity pipelines
def activity_pipeline_query(images, annotator, activity_category):
    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(activity_checked_by__in=[annotator]) & ~Q(activity_skipped_by__in=[annotator]),
        # Image hasn't completed the Activity Pipeline
        activity_pipeline_complete=False,
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
    )

    # Filter for animals or humans based on the category passed into the view
    if activity_category == CATEGORY_HUMAN:
        images = images.filter(has_humans=True)
    else:
        images = images.filter(has_wild_animals=True)

    images = images.order_by("-upload__priority", "upload__camera_station", "trigger_timestamp")

    images = staff_review_query_filter(images, annotator)

    return images


def gather_queue_images(self, queue, queue_name, queue_key, annotator, activity_category):
    # Get images based on the following set of filters
    images = Image.objects.filter(**self.filterset)

    # Filter using specified pipeline criteria
    if SPECIES_QUEUE_NAME in queue_name:
        images = species_pipeline_query(images=images, annotator=annotator)
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        images = activity_pipeline_query(images=images, annotator=annotator, activity_category=activity_category)
    else:
        logging.error(f"Invalid queue name provided to query function: {queue_name}")

    # Get the image stack based on stack size
    images = images[: settings.ANNOTATION_QUEUE_SIZE]

    # Get the image ids & convert to string
    image_ids = [str(image.id) for image in images]

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


def get_next_queue_image(self, context, queue):
    # Exists if user is returning to a previous image
    return_to_image_id = self.request.session.pop("return_to_image_id", None)
    context["is_reannotation"] = return_to_image_id is not None

    # If not returning to prev. image,
    # get the next image_id from the existing queue
    return return_to_image_id if return_to_image_id else queue["images"][queue["index"]], return_to_image_id


# Skip images completed or made ineligible by other annotators since the queue was built
def skip_ineligible_images(queue_name, queue):
    pipeline_completed = True
    pipeline_eligible = True

    while (pipeline_completed or not pipeline_eligible) and queue["index"] < len(queue["images"]):
        image = Image.objects.get(id=queue["images"][queue["index"]])

        # Recalculate flags on immediate images (alternative to running script on everything again)
        # Remove this when flags for images with rejected bboxes have been updated
        if (
            BoundingBox.objects.annotate(reject_count=Count("rejected_by"))
            .filter(image=image, reject_count__gt=0)
            .exists()
            or image.category_pipeline_complete is False
        ):
            logging.info("Recalculating flags...")
            calculateCategoryAnnotationFlags(image)
            calculateSpeciesAnnotationFlags(image)
            calculateActivityAnnotationFlags(image)
            image.save()

        if SPECIES_QUEUE_NAME in queue_name:
            pipeline_completed = image.species_pipeline_complete
            pipeline_eligible = BoundingBox.objects.filter(image=image).exists()
        elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
            pipeline_completed = image.activity_pipeline_complete
            pipeline_eligible = image.has_humans or image.has_wild_animals
        else:
            break

        if pipeline_completed:
            queue["index"] += 1
            logging.info(f"Queue image {image.id} was completed by another annotator. Skipping to next image.")
        elif not pipeline_eligible:
            queue["index"] += 1
            logging.info(f"Queue image {image.id} was made ineligible by another annotator. Skipping to next image.")
        elif auto_flag_for_staff(image):
            queue["index"] += 1
            logging.info(
                f"Queue image {image.id} skipped by many annotators. Flagging for staff and skipping to next image."
            )

    settings.DATASTORE_CLIENT.put(queue)

    return image


def get_annotation_history(context, queue, queue_name, annotator):
    HISTORY_LENGTH = 10

    image_history = Image.objects.filter(id__in=queue["images"])
    context["previous_annotations"] = []

    if SPECIES_QUEUE_NAME in queue_name:
        image_history.filter(Q(species_checked_by__in=[annotator]) | Q(species_skipped_by__in=[annotator]))
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        image_history.filter(Q(activity_checked_by__in=[annotator]) | Q(activity_skipped_by__in=[annotator]))

    context["previous_queue_images"] = image_history.order_by("-modified")[:HISTORY_LENGTH]

    for image in context["previous_queue_images"]:
        if SPECIES_QUEUE_NAME in queue_name:
            previous_annotations = Species.objects.filter(
                Q(created_by=annotator) | Q(accepted_by__in=[annotator]), bounding_box__image=image
            ).values("name__name")
        elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
            previous_annotations = Activity.objects.filter(
                Q(created_by=annotator) | Q(accepted_by__in=[annotator]), bounding_box__image=image
            ).values("name")
        else:
            pass

        if previous_annotations.count() == 0:
            context["previous_annotations"].append("None")
        else:
            context["previous_annotations"].append(
                ", ".join(anno for anno in set(list(annotation.values())[0] for annotation in previous_annotations))
            )

    context["previous_annotation_info"] = zip(context["previous_queue_images"], context["previous_annotations"])


def get_burst_images(context, queue):
    BURST_TIME_THRESHOLD = 120

    images = []
    prev_timestamp = Image.objects.get(id=queue["images"][queue["index"]]).trigger_timestamp

    # Check only the next images in queue
    for image_id in queue["images"][queue["index"] + 1 :]:
        image = Image.objects.get(id=image_id)
        time_diff = image.trigger_timestamp - prev_timestamp

        # If the times are close enough, consider it as potentially part of a burst
        if time_diff > datetime.timedelta(seconds=BURST_TIME_THRESHOLD):
            break
        else:
            images.append(image)

    context["images_w_boxes"] = [
        [image_obj, BoundingBox.objects.valid_or_uncertain().filter(image=image_obj)] for image_obj in images
    ]


# Retrieves data to pass to the views through context (namely queue images and annotations info).
def populate_view_context(queue_name, context, self, activity_category=None):
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

    return_to_image_id = None

    if queue_available:
        image_id, return_to_image_id = get_next_queue_image(self=self, context=context, queue=queue)
    else:
        # Serve the first image
        queue, image_id = gather_queue_images(
            self=self,
            queue=queue,
            queue_name=queue_name,
            queue_key=queue_key,
            annotator=annotator,
            activity_category=activity_category,
        )

    # If there is a valid image, add bounding box information
    if image_id:
        image = Image.objects.get(id=image_id)

        if return_to_image_id is None:
            skip_result = skip_ineligible_images(queue_name=queue_name, queue=queue)
            image = skip_result if skip_result else image

        context["image"] = image
        context["social_media_worthy"] = image.social_media_worthy
        context["staff_review_needed"] = image.staff_review_needed
        context["bounding_boxes"] = get_valid_or_uncertain_bboxes(image=image)
        context["queue_index"] = queue["index"]
        context["queue_length"] = len(queue["images"])

        # Calculate image luma
        context["luma_adjustment"] = calculate_image_luma(image, context["bounding_boxes"])

        # Get previously annotated images and their information
        get_annotation_history(context, queue, queue_name, annotator)

        # Gather surrounding context images
        try:
            get_context_images(queue=queue, context=context)
        except Exception:
            logging.info(f"Failed to get context images for image {image_id}.")

        # Gather all annotations for bounding boxes to display in admin view.
        get_all_annotations(image=image, context=context)

        # Get user annotation count
        context["user_annotation_count"] = get_or_set_annotation_count(
            request=self.request, queue_name=queue_name, annotator=annotator
        )

        # Get burst images for multi-image tagging
        get_burst_images(context=context, queue=queue)
    else:
        image = None
        context["image"] = None
        context["bounding_boxes"] = []

    context["species_list"] = SpeciesName.objects.filter(~Q(name=UNANNOTATED_CATEGORY))
    context["birds_list"] = SpeciesName.objects.filter(is_bird=True)
    context["activity_list"] = ActivityType.objects.filter(category=activity_category)
    context["custom_annotations"] = custom_annotations

    if SPECIES_QUEUE_NAME in queue_name:
        context["pipeline"] = "species"
    elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name:
        context["pipeline"] = "animal activity"
    elif ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
        context["pipeline"] = "human activity"


def auto_flag_for_staff(image):
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

    return [bbox_obj for bbox_obj, bbox_values in zipped_querysets if bbox_values.get("status") != "Invalid"]


def get_context_images(queue, context):
    CONTEXT_AMOUNT = 20

    context["context_images"] = list(
        Image.objects.filter(
            upload__camera_station=context["image"].upload.camera_station,
            trigger_timestamp__lt=context["image"].trigger_timestamp,
            trigger_timestamp__gt=context["image"].trigger_timestamp - datetime.timedelta(minutes=10),
        )[:CONTEXT_AMOUNT]
    ) + list(
        Image.objects.filter(
            upload__camera_station=context["image"].upload.camera_station,
            trigger_timestamp__gte=context["image"].trigger_timestamp,
            trigger_timestamp__lt=context["image"].trigger_timestamp + datetime.timedelta(minutes=10),
        )[:CONTEXT_AMOUNT]
    )


def get_all_annotations(image, context):
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


# Sets filterset for the views' GET function
def set_view_filterset(self):
    start_date = self.request.GET.get("start_date")
    end_date = self.request.GET.get("end_date")
    camera_id = None if self.request.GET.get("camera_id") == "None" else self.request.GET.get("camera_id")
    macrosite_name = self.request.GET.get("macrosite_name")

    self.filterset = get_filter_params(start_date, end_date, macrosite_name, camera_id)


class AnnotateSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/species.html"

    def get(self, request, *args, **kwargs):
        set_view_filterset(self)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        populate_view_context(SPECIES_QUEUE_NAME, context, self)

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

    annotation_description = None

    # Process the annotations
    if queue_name == SPECIES_QUEUE_NAME:
        annotation_description = "Species"
        success = process_species_annotations(
            image_id,
            annotations,
            initial_bboxes,
            request.user,
            social_media_worthy_vote,
            staff_review_needed,
            skip=skip,
        )

    elif queue_name == ACTIVITY_ANIMAL_QUEUE_NAME:
        annotation_description = "Animal activity"
        success = process_activity_annotations(
            image_id,
            annotations,
            initial_bboxes,
            request.user,
            social_media_worthy_vote,
            staff_review_needed,
            skip=skip,
        )

    elif queue_name == ACTIVITY_HUMAN_QUEUE_NAME:
        annotation_description = "Human activity"
        success = process_activity_annotations(
            image_id,
            annotations,
            initial_bboxes,
            request.user,
            social_media_worthy_vote,
            staff_review_needed,
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
            count = len(annotations)

            get_or_set_annotation_count(
                request=request,
                queue_name=queue_name,
                annotator=annotator,
                annotation_num=count,
            )

            # Use an object to track each day, for each annotator, for each pipeline
            today = datetime.datetime.today()

            counter = AnnotationCounter.objects.filter(
                annotator=annotator, annotation_type=annotation_type, created__day=today.day, created__month=today.month
            ).first()

            if counter:
                counter.annotation_count += count
                counter.image_count += 1
                counter.save()
            else:
                AnnotationCounter.objects.create(
                    annotator=annotator, annotation_type=annotation_type, annotation_count=count, image_count=1
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
    # Alternative to .annotate() to calculate object properties, which returns incorrect data due to multiple aggregations.
    # Takes a zip object containing a list of annotation objects to reference,
    # and its .value() list to append data to.

    for obj, annotation in zipped_querysets:
        annotation["accepted_count"] = obj.accepted_by.count() + (1 if obj.created_by.type == "human" else 0)
        annotation["rejected_count"] = obj.rejected_by.count()

        annotation["vote_difference"] = annotation.get("accepted_count") - annotation.get("rejected_count")

        annotation["has_staff_or_expert_vote"] = bool(
            obj.accepted_by.filter(STAFF_OR_EXPERT_CHECK).exists()
            or (obj.created_by.human and (obj.created_by.human.is_staff or obj.created_by.human.is_expert))
        )

        staff_or_expert_rejection = obj.rejected_by.filter(STAFF_OR_EXPERT_CHECK).exists()
        correlated_obj_rejected = False

        if hasattr(obj, "bounding_box"):
            bbox_obj = BoundingBox.objects.filter(id=obj.bounding_box.id)
            bbox_values = bbox_obj.values()

            zipped_bbox_querysets = list(zip(bbox_obj, bbox_values))
            annotate(zipped_bbox_querysets)

            correlated_obj_rejected = zipped_bbox_querysets[0][1].get("status") == "Invalid"

        if (
            annotation.get("vote_difference") > VOTE_THRESHOLD
            and not staff_or_expert_rejection
            and not correlated_obj_rejected
        ) or annotation["has_staff_or_expert_vote"]:
            annotation["status"] = "Valid"
        elif (
            annotation.get("vote_difference") < -VOTE_THRESHOLD or staff_or_expert_rejection or correlated_obj_rejected
        ):
            annotation["status"] = "Invalid"
        else:
            annotation["status"] = "Uncertain"


# Category Flag Checks
def calculateCategoryAnnotationFlags(image):
    category_objs = Category.objects.filter(bounding_box__image=image)
    category_annotations = category_objs.values()

    bounding_box_objs = BoundingBox.objects.filter(image=image)
    bounding_box_annotations = bounding_box_objs.values()

    zipped_bbox_querysets = list(zip(bounding_box_objs, bounding_box_annotations))
    annotate(zipped_bbox_querysets)

    zipped_querysets = list(zip(category_objs, category_annotations))
    annotate(zipped_querysets)

    category_has_uncertain_annotation = any(
        category[1].get("status") == "Uncertain" for category in zipped_querysets
    ) or any(bbox[1].get("status") == "Uncertain" for bbox in zipped_bbox_querysets)

    has_staff_or_expert_vote = any(category[1].get("has_staff_or_expert_vote") is True for category in zipped_querysets)

    not_invalid_bbox_count_gt = BoundingBox.objects.filter(image=image).count() > 0 and any(
        bbox[1].get("status") != "Invalid" for bbox in zipped_bbox_querysets
    )

    all_bboxes_have_category = not category_objs.filter(name=UNANNOTATED_CATEGORY).exists()

    # Save bbox validity status
    for bbox in zipped_bbox_querysets:
        bbox[0].validity = bbox[1].get("status")
        bbox[0].save()
        logging.info(f"Validity saved as '{bbox[0].validity}' for bbox {bbox[0].id}.'")

    if (
        not category_has_uncertain_annotation
        and image.processed
        and not_invalid_bbox_count_gt
        and all_bboxes_have_category
    ):
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
            "all_bboxes_have_category": all_bboxes_have_category,
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
    species_objs = Species.objects.filter(bounding_box__image__id=image.id)
    species_annotations = species_objs.values()

    zipped_querysets = list(zip(species_objs, species_annotations))
    annotate(zipped_querysets)

    species_has_uncertain_annotation = any(species[1].get("status") == "Uncertain" for species in zipped_querysets)

    species_valid_annotations = [
        species_obj
        for species_obj, species_annotation in zipped_querysets
        if species_annotation.get("status") == "Valid"
    ]

    species_has_valid_annotation = len(species_valid_annotations) > 0

    has_staff_or_expert_vote = any(species[1].get("has_staff_or_expert_vote") is True for species in zipped_querysets)

    annotation_checked_by_gte = image.species_checked_by.all().count() >= MAX_VOTES_PER_IMAGE

    all_bboxes_have_species = not species_objs.filter(name__name=UNANNOTATED_CATEGORY).exists()

    if (
        not species_has_uncertain_annotation
        and species_has_valid_annotation
        and (annotation_checked_by_gte or has_staff_or_expert_vote)
        and image.processed
        and all_bboxes_have_species
    ):
        image.has_wild_animals = species_annotations.filter(name__species_group="WILD").exists()
        image.species_pipeline_complete = True
    else:
        # Reset the flags if conditions not met (i.e. retroactively send image back)
        image.species_pipeline_complete = False
        image.has_wild_animals = False

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
            "all_bboxes_have_species": all_bboxes_have_species,
        },
        "pipeline_flags": {
            "has_wild_animals": image.has_wild_animals,
            "species_pipeline_complete": image.species_pipeline_complete,
        },
    }

    return species_debug_data


# Activity Flag Checks
def calculateActivityAnnotationFlags(image):
    activity_objs = Activity.objects.filter(bounding_box__image__id=image.id)
    activity_annotations = activity_objs.values()

    zipped_querysets = list(zip(activity_objs, activity_annotations))
    annotate(zipped_querysets)

    activity_has_uncertain_annotation = any(activity[1].get("status") == "Uncertain" for activity in zipped_querysets)

    activity_has_valid_annotation = any(activity[1].get("status") == "Valid" for activity in zipped_querysets)

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
