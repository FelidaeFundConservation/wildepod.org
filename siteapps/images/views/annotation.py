import datetime
import json
import logging

import numpy as np
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
from django.db.models.functions import Coalesce
from django.http.response import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import FormView
from django.views.generic.base import TemplateView, View
from images.forms import AnnotationForm
from images.models import Activity, ActivityType, Annotator, BoundingBox, Category, Image, Species, SpeciesName
from images.models.custom_fields import get_filter_params
from images.processors import process_activity_annotations, process_md_annotations, process_species_annotations
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 2
VOTE_THRESHOLD = 1

CATEGORY_ANIMAL = "animal"
CATEGORY_HUMAN = "human"
CUSTOM_PREFIX = "Custom"
OBJECTS_QUEUE_NAME = "AnnotateObjectsQueue"
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


# Filter criteria for an image to appear in the Object/Blank pipeline
def object_pipeline_query(images, annotator):
    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(bbox_checked_by__in=[annotator]) & ~Q(bbox_skipped_by__in=[annotator]),
        # Image has at least one bounding box tagged by MegaDetector above the predetermined threshold
        Exists(
            BoundingBox.objects.filter(image=OuterRef("pk"))
            .annotate(
                # TODO: This calculation can happen after MegaDetector processing, and we can set a flag.
                confidence_threshold=Case(
                    When(created_by__type="bot", then="created_by__bot__threshold"),
                    default=0.0,
                ),
                # TODO: These calculations should happen after the annotations are done in the precompute flag methods.
                num_accepted=Coalesce(Count("accepted_by", distinct=True), 0),
                num_rejected=Coalesce(Count("rejected_by", distinct=True), 0),
                num_accepted_expert=Case(
                    When(
                        Exists(
                            Annotator.objects.filter(
                                Q(human__is_staff=True) | Q(human__is_expert=True),
                                accepted_annotation=OuterRef("pk"),
                            )
                        ),
                        then=Value(1),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                num_rejected_expert=Case(
                    When(
                        Exists(
                            Annotator.objects.filter(
                                Q(human__is_staff=True) | Q(human__is_expert=True),
                                rejected_annotation=OuterRef("pk"),
                            )
                        ),
                        then=Value(1),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # Expert votes have a multiplier so they override any uncertainity about the bounding box
                vote_diff=F("num_accepted")
                + F("num_accepted_expert") * 2
                - F("num_rejected")
                - F("num_rejected_expert") * 2,
                vote_uncertain=ExpressionWrapper(
                    Q(vote_diff__lt=settings.NUM_ACCEPTS_OVER_REJECTS)
                    & Q(vote_diff__gt=-settings.NUM_ACCEPTS_OVER_REJECTS),
                    output_field=models.BooleanField(),
                ),
            )
            .filter(confidence__gte=F("confidence_threshold"), vote_uncertain=True)
        ),
        # Image hasn't completed the Category/Object Pipeline
        category_pipeline_complete=False,
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
    ).order_by("-upload__priority", "upload__camera_station", "trigger_timestamp")

    return images


# Filter criteria for an image to appear in the Species pipeline
def species_pipeline_query(images, annotator):
    images = images.filter(
        # It must not be checked or skipped by the current annotator
        ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator]),
        # Image hasn't completed the Species Pipeline
        species_pipeline_complete=False,
        # Image has animals
        has_animals=True,
        # Image has been preprocessed and we can use precomputed flags
        use_precomputed_flags=True,
    ).order_by("-upload__priority", "upload__camera_station", "trigger_timestamp")

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

    return images


def gather_queue_images(self, queue, queue_name, queue_key, annotator, activity_category):
    # Get images based on the following set of filters
    images = Image.objects.filter(**self.filterset)

    # Filter using specified pipeline criteria
    if OBJECTS_QUEUE_NAME in queue_name:
        images = object_pipeline_query(images=images, annotator=annotator)
    elif SPECIES_QUEUE_NAME in queue_name:
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
    return_to_image_id = self.request.session.get("return_to_image_id")
    context["is_reannotation"] = return_to_image_id is not None

    # Clear the return image id
    self.request.session["return_to_image_id"] = None

    # If not returning to prev. image,
    # get the next image_id from the existing queue
    return return_to_image_id if return_to_image_id else queue["images"][queue["index"]]


# Skip images completed by other annotators since the queue was built
def skip_completed_images(queue_name, queue):
    pipeline_completed = True

    while pipeline_completed and queue["index"] < len(queue["images"]):
        image = Image.objects.get(id=queue["images"][queue["index"]])

        if OBJECTS_QUEUE_NAME in queue_name:
            pipeline_completed = image.category_pipeline_complete
        elif SPECIES_QUEUE_NAME in queue_name:
            pipeline_completed = image.species_pipeline_complete
        elif ACTIVITY_ANIMAL_QUEUE_NAME in queue_name or ACTIVITY_HUMAN_QUEUE_NAME in queue_name:
            pipeline_completed = image.activity_pipeline_complete
        else:
            break

        if pipeline_completed:
            queue["index"] += 1
            logging.info(f"Queue image {image.id} was completed by another annotator. Skipping to next image.")

    settings.DATASTORE_CLIENT.put(queue)

    return image


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
        image_id = get_next_queue_image(self=self, context=context, queue=queue)
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
            skip_result = skip_completed_images(queue_name=queue_name, queue=queue)
            image = skip_result if skip_result else image

        context["image"] = image
        context["social_media_worthy"] = image.social_media_worthy
        context["staff_review_needed"] = image.staff_review_needed
        context["bounding_boxes"] = get_valid_or_uncertain_bboxes(image=image)
        context["queue_index"] = queue["index"]
        context["queue_length"] = len(queue["images"])
    else:
        image = None
        context["image"] = None
        context["bounding_boxes"] = []

    context["species_list"] = SpeciesName.objects.filter(~Q(name=UNANNOTATED_CATEGORY))
    context["activity_list"] = ActivityType.objects.filter(category=activity_category)
    context["custom_annotations"] = custom_annotations

    # Gather surrounding context images
    get_context_images(queue=queue, context=context)

    # Gather all annotations for bounding boxes to display in admin view.
    get_all_annotations(image=image, context=context)


# Filter out the rejected bboxes
def get_valid_or_uncertain_bboxes(image):
    bounding_boxes = BoundingBox.objects.filter(image__id=image.id)
    bounding_box_values = bounding_boxes.values()

    zipped_querysets = list(zip(bounding_boxes, bounding_box_values))
    annotate(zipped_querysets)

    return [bbox_obj for bbox_obj, bbox_values in zipped_querysets if bbox_values.get("status") != "Rejected"]


def get_context_images(queue, context):
    CONTEXT_AMOUNT = 25

    context["context_images"] = list(
        Image.objects.filter(
            upload__camera_station=context["image"].upload.camera_station,
            trigger_timestamp__lt=context["image"].trigger_timestamp,
            trigger_timestamp__gt=context["image"].trigger_timestamp - datetime.timedelta(hours=1),
        )[:CONTEXT_AMOUNT]
    ) + list(
        Image.objects.filter(
            upload__camera_station=context["image"].upload.camera_station,
            trigger_timestamp__gte=context["image"].trigger_timestamp,
            trigger_timestamp__lt=context["image"].trigger_timestamp + datetime.timedelta(hours=1),
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
                queue_name = CUSTOM_PREFIX + OBJECTS_QUEUE_NAME
                url = (
                    reverse("images:annotate_objects")
                    + f"?custom=true&start_date={start_date}&end_date={end_date}&macrosite_name={macrosite_name}&camera_id={camera_id}"
                )

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


class AnnotateObjectsView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/objects.html"

    def get(self, request, *args, **kwargs):
        set_view_filterset(self)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        populate_view_context(OBJECTS_QUEUE_NAME, context, self)

        return context


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
def annotation_processor(queue_name, request):
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
    if queue_name == OBJECTS_QUEUE_NAME:
        annotation_description = "Bounding box"
        success = process_md_annotations(
            image_id, annotations, initial_bboxes, request.user, social_media_worthy_vote, staff_review_needed, skip
        )

    elif queue_name == SPECIES_QUEUE_NAME:
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


class MDAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return annotation_processor(OBJECTS_QUEUE_NAME, request)


class SpeciesAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return annotation_processor(SPECIES_QUEUE_NAME, request)


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

        return annotation_processor(queue_name, request)


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
        annotation["accepted_count"] = obj.accepted_by.count()
        annotation["rejected_count"] = obj.rejected_by.count()

        annotation["vote_difference"] = annotation.get("accepted_count") - annotation.get("rejected_count")

        annotation["has_staff_or_expert_vote"] = bool(
            obj.accepted_by.filter(Q(human__is_staff=True) | Q(human__is_expert=True)).exists()
            or (obj.created_by.human and obj.created_by.human.is_staff)
        )

        if annotation.get("vote_difference") > VOTE_THRESHOLD:
            annotation["status"] = "Valid"
        elif annotation.get("vote_difference") < -VOTE_THRESHOLD:
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

    bbox_count_gt = BoundingBox.objects.filter(image=image).count() > 0

    all_bboxes_have_category = not category_objs.filter(name=UNANNOTATED_CATEGORY).exists()

    if (
        not category_has_uncertain_annotation
        and image.processed
        and bbox_count_gt
        and all_bboxes_have_category
        or (has_staff_or_expert_vote and all_bboxes_have_category)
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
            "bounding_boxes_gte_zero": bbox_count_gt,
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

    # TODO: Use the SpeciesName species_group field instead once they're set for all objects.
    NON_WILD_SPECIES = [
        "Cyclist",
        "Domestic cat",
        "Domestic dog",
        "Domestic horse",
        "Goat (domestic)",
        "Horse rider",
        "Human",
        "Motorized vehicle",
        "Non motorized vehicle (bike)",
        "Sheep (domestic)",
        "Unknown",
    ]

    # Fix the object annotation retroactively if applicable
    # If species is tagged 'human,' but object is marked 'animal,' change to 'person,' and vice versa.
    ANIMAL_CATEGORY_LIST = list(SpeciesName.objects.filter(species_group__in=["WILD", "DOMESTIC"]))
    HUMAN_CATEGORY_LIST = list(SpeciesName.objects.filter(species_group="HUMAN"))

    for species in species_valid_annotations:
        try:
            # Get the valid category to replace (assuming there should only ever be 1)
            category = (
                Category.objects.filter(bounding_box=species.bounding_box)
                .annotate(
                    accepted_count=Count("accepted_by"),
                    rejected_count=Count("rejected_by"),
                    expert_accepted_count=Count(
                        Case(
                            When(
                                Q(created_by__human__is_staff=True)
                                | Q(accepted_by__human__is_staff=True)
                                | Q(created_by__human__is_expert=True)
                                | Q(accepted_by__human__is_expert=True),
                                then=1,
                            ),
                            output_field=IntegerField(),
                        )
                    ),
                    expert_rejected_count=Count(
                        Case(
                            When(Q(rejected_by__human__is_staff=True) | Q(rejected_by__human__is_expert=True), then=1),
                            output_field=IntegerField(),
                        )
                    ),
                    has_staff_vote=Count(
                        Case(
                            When(Q(created_by__human__is_staff=True) | Q(accepted_by__human__is_staff=True), then=1),
                            output_field=BooleanField(),
                        )
                    ),
                    vote_difference=(
                        (F("accepted_count") - F("expert_accepted_count"))
                        + (F("expert_accepted_count") * STAFF_OR_EXPERT_VOTE_MULTIPLIER)
                    )
                    - (
                        (F("rejected_count") - F("expert_rejected_count"))
                        + (F("expert_rejected_count") * STAFF_OR_EXPERT_VOTE_MULTIPLIER)
                    ),
                    status=Case(
                        When(
                            Q(vote_difference__gt=VOTE_THRESHOLD) | Q(has_staff_vote=True),
                            then=Value("Valid"),
                        ),
                        When(vote_difference__lt=-VOTE_THRESHOLD, then=Value("Invalid")),
                        default=Value("Uncertain"),
                        output_field=models.CharField(),
                    ),
                )
                .get(status="Valid")
            )

        except Exception as e:
            logging.error(f"Couldn't find the valid category for the bbox: {e}")
            # This should only happen if the category wasn't valid
            # and shouldn't have been in the species pipeline in the first place
            continue

        # Replace the category based on the valid species annotated
        is_same_bbox = category.bounding_box == species.bounding_box

        if category and category.name == "person" and species.name in ANIMAL_CATEGORY_LIST and is_same_bbox:
            category.name = "animal"
        elif category and category.name == "animal" and species.name in HUMAN_CATEGORY_LIST and is_same_bbox:
            category.name = "person"

        category.save()

    if (
        not species_has_uncertain_annotation
        and species_has_valid_annotation
        and image.has_animals
        and annotation_checked_by_gte
        and image.processed
        and all_bboxes_have_species
        or (has_staff_or_expert_vote and all_bboxes_have_species)
    ):
        image.has_wild_animals = species_annotations.filter(~Q(name__name__in=NON_WILD_SPECIES)).exists()
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
        and annotation_checked_by_gte
        and image.processed
        or has_staff_or_expert_vote
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
