import datetime
import json
import logging

import numpy as np
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Exists, OuterRef, Q
from django.http.response import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import FormView
from django.views.generic.base import TemplateView, View
from images.forms import AnnotationForm
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
    get_object_annotation_images,
)
from images.models.custom_fields import get_filter_params
from images.processors import process_activity_annotations, process_md_annotations, process_species_annotations
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 2
CATEGORY_ANIMAL = "animal"
CATEGORY_HUMAN = "human"
CUSTOM_PREFIX = "Custom"
OBJECTS_QUEUE_NAME = "AnnotateObjectsQueue"
SPECIES_QUEUE_NAME = "AnnotateSpeciesQueue"
ACTIVITY_HUMAN_QUEUE_NAME = "AnnotateHumanBehaviorQueue"
ACTIVITY_ANIMAL_QUEUE_NAME = "AnnotateAnimalActivityQueue"


class BboxAnnotationInfo:
    def __init__(self, id, categories, species, activities):
        self.id = id
        self.categories = categories
        self.species = species
        self.activities = activities


# TODO: Clean up this code
# TODO: There are several common bits of code across the three annotation views and should be refactored
class AnnotateObjectsView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/objects.html"

    def get(self, request, *args, **kwargs):
        station = None if self.request.GET.get("camera_id") == "None" else self.request.GET.get("camera_id")

        self.filterset = {
            "start_date": self.request.GET.get("start_date"),
            "end_date": self.request.GET.get("end_date"),
            "station": station,
            "macrosite": self.request.GET.get("macrosite_name"),
            "annotator": self.request.user,
        }
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Check if we're doing custom annotations
        custom_annotations = self.request.GET.get("custom", None) == "true"

        # Get the annotation queue cached in the datastore
        queue_name = OBJECTS_QUEUE_NAME
        if custom_annotations:
            queue_name = CUSTOM_PREFIX + queue_name
        queue_key = settings.DATASTORE_CLIENT.key(queue_name, str(self.request.user.id))
        queue = settings.DATASTORE_CLIENT.get(queue_key)
        # Check if we have a valid cached queue of images
        queue_available = (
            queue
            and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
            and queue["index"] < len(queue["images"])
        )

        if queue_available:
            # Get the next image_id from the existing queue
            image_id = queue["images"][queue["index"]]
        else:
            # Get the images to annotate. Check raw sql to see how this is done
            images = get_object_annotation_images(**self.filterset, queue_size=settings.ANNOTATION_QUEUE_SIZE)

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

            # Serve the first image
            image_id = image_ids[0] if image_ids else None

        # If there is a valid image, add bounding box information
        if image_id:
            image = Image.objects.get(id=image_id)
            context["image"] = image
            context["social_media_worthy"] = image.social_media_worthy
            context["staff_review_needed"] = image.staff_review_needed
            bounding_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=image)
            context["bounding_boxes"] = bounding_boxes
            context["queue_index"] = queue["index"]
            context["queue_length"] = len(queue["images"])
        else:
            context["image"] = None
            context["bounding_boxes"] = []

        # Gather surrounding context images.
        CONTEXT_AMOUNT = 4

        lowerIndex = queue["index"] - CONTEXT_AMOUNT
        upperIndex = queue["index"] + CONTEXT_AMOUNT

        lowerIndex = 0 if (lowerIndex < 0) else lowerIndex
        upperIndex = len(queue["images"]) if (upperIndex > len(queue["images"])) else upperIndex

        context["context_images"] = [
            Image.objects.get(id=image_id) for image_id in queue["images"][lowerIndex:upperIndex]
        ]

        # Gather all annotations for bounding boxes.
        try:
            bboxes = BoundingBox.objects.filter(image=queue["images"][queue["index"]])
        except (ObjectDoesNotExist, IndexError):
            bboxes = []

        infoList = []

        for bbox in bboxes:
            categories = Category.objects.filter(bounding_box=bbox)
            species = Species.objects.filter(bounding_box=bbox)
            activities = Activity.objects.filter(bounding_box=bbox)

            infoList.append(BboxAnnotationInfo(bbox.id, categories, species, activities))

        context["bbox_all_annotations"] = infoList
        context["custom_annotations"] = custom_annotations

        return context


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


# TODO: Clean up this code
class AnnotateSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/species.html"

    def get(self, request, *args, **kwargs):
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        camera_id = None if self.request.GET.get("camera_id") == "None" else self.request.GET.get("camera_id")
        macrosite_name = self.request.GET.get("macrosite_name")

        self.filterset = get_filter_params(start_date, end_date, macrosite_name, camera_id)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Check if we're doing custom annotations
        custom_annotations = self.request.GET.get("custom", None) == "true"

        # Get the annotation queue cached in the datastore
        queue_name = SPECIES_QUEUE_NAME
        if custom_annotations:
            queue_name = CUSTOM_PREFIX + queue_name
        queue_key = settings.DATASTORE_CLIENT.key(queue_name, str(self.request.user.id))
        queue = settings.DATASTORE_CLIENT.get(queue_key)
        # Check if we have a valid cached queue of images
        queue_available = (
            queue
            and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
            and queue["index"] < len(queue["images"])
        )

        if queue_available:
            # Get the image id
            image_id = queue["images"][queue["index"]]
        else:
            # Get images based on the following set of filters
            images = Image.objects.annotated().filter(**self.filterset)

            images = images.filter(
                # It must not be checked or skipped by the current annotator
                ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator]),
                # There must be at least one or more "valid" bounding boxes
                Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                # There must be no uncertain bounding boxes for the image
                ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                # TODO: Fix the line below
                # This is a quick and dirty hack to only ever show an image if there is at least
                # one bounding box that has at least one category tagged as an animal linked to it
                # It should work for most of the time but is not always accurate and will generate false positives
                # Must be fixed
                Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk"))),
                # If a staff vote exists for the species, we'll no longer show it
                ~Exists(
                    BoundingBox.objects.filter(
                        Exists(
                            Species.objects.filter(
                                Exists(
                                    Annotator.objects.filter(
                                        Q(human__is_staff=True) | Q(human__is_expert=True),
                                        accepted_species_annotation=OuterRef("pk"),
                                    )
                                ),
                                bounding_box=OuterRef("pk"),
                            )
                        ),
                        image=OuterRef("pk"),
                    )
                ),
                # Show image only if checked by fewer people
                num_species_checked_by__lt=MAX_VOTES_PER_IMAGE,
                # Image must be marked as processed
                processed=True,
            ).order_by(
                "-upload__priority",
                "upload__camera_station",
                "trigger_timestamp",
                "num_species_checked_by",
                "num_objects",
            )
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

            # Serve the first image
            image_id = image_ids[0] if image_ids else None

        # If there is a valid image, add bounding box information
        if image_id:
            image = Image.objects.get(id=image_id)
            context["image"] = image
            context["social_media_worthy"] = image.social_media_worthy
            context["staff_review_needed"] = image.staff_review_needed
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes
        else:
            context["image"] = None
            context["bounding_boxes"] = []

        context["species_list"] = SpeciesName.objects.all()

        # Gather surrounding context images.
        CONTEXT_AMOUNT = 4

        lowerIndex = queue["index"] - CONTEXT_AMOUNT
        upperIndex = queue["index"] + CONTEXT_AMOUNT

        lowerIndex = 0 if (lowerIndex < 0) else lowerIndex
        upperIndex = len(queue["images"]) if (upperIndex > len(queue["images"])) else upperIndex

        context["context_images"] = [
            Image.objects.get(id=image_id) for image_id in queue["images"][lowerIndex:upperIndex]
        ]

        # Gather all annotations for bounding boxes.
        try:
            bboxes = BoundingBox.objects.filter(image=queue["images"][queue["index"]])
        except (ObjectDoesNotExist, IndexError):
            bboxes = []

        infoList = []

        for bbox in bboxes:
            categories = Category.objects.filter(bounding_box=bbox)
            species = Species.objects.filter(bounding_box=bbox)
            activities = Activity.objects.filter(bounding_box=bbox)

            infoList.append(BboxAnnotationInfo(bbox.id, categories, species, activities))

        context["bbox_all_annotations"] = infoList
        context["custom_annotations"] = custom_annotations

        return context


# TODO: Clean up this code
class AnnotateActivityView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/activity.html"

    def get(self, request, *args, **kwargs):
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        camera_id = None if self.request.GET.get("camera_id") == "None" else self.request.GET.get("camera_id")
        macrosite_name = self.request.GET.get("macrosite_name")
        self.filterset = get_filter_params(start_date, end_date, macrosite_name, camera_id)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        activity_category = self.request.GET.get("annotation_choice") or self.kwargs["category"]
        context["activity_category"] = activity_category

        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Check if we're doing custom annotations
        custom_annotations = self.request.GET.get("custom", None) == "true"

        # Get the annotation queue based on the selections
        if context["activity_category"] == CATEGORY_HUMAN:
            queue_name = ACTIVITY_HUMAN_QUEUE_NAME
        else:
            queue_name = ACTIVITY_ANIMAL_QUEUE_NAME

        if custom_annotations:
            queue_name = CUSTOM_PREFIX + queue_name
        queue_key = settings.DATASTORE_CLIENT.key(queue_name, str(self.request.user.id))
        queue = settings.DATASTORE_CLIENT.get(queue_key)
        # Check if we have a valid cached queue of images
        queue_available = (
            queue
            and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
            and queue["index"] < len(queue["images"])
        )

        # If a valid object exists and if it is not expired and if the index points to a valid image, serve it
        if queue_available:
            # Get the image id
            image_id = queue["images"][queue["index"]]
        else:
            # Get images based on the following set of filters
            images = Image.objects.annotated().filter(**self.filterset)
            images = images.filter(
                # It must not be checked or skipped by the current annotator
                ~Q(activity_checked_by__in=[annotator]) & ~Q(activity_skipped_by__in=[annotator]),
                # There must be at least one or more "valid" bounding boxes
                Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                # There must be no uncertain bounding boxes for the image
                ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                # If a staff vote exists for the activity, we'll no longer show it
                ~Exists(
                    BoundingBox.objects.filter(
                        Exists(
                            Activity.objects.filter(
                                Exists(
                                    Annotator.objects.filter(
                                        Q(human__is_staff=True) | Q(human__is_expert=True),
                                        accepted_species_annotation=OuterRef("pk"),
                                    )
                                ),
                                bounding_box=OuterRef("pk"),
                            )
                        ),
                        image=OuterRef("pk"),
                    )
                ),
                # Image must be marked as processed
                processed=True,
                num_activity_checked_by__lt=MAX_VOTES_PER_IMAGE,
            )

            # Filter for animals or humans based on the category passed into the view
            # TODO: The same issues with the species annotation filter exists here too
            # We only use one bounding box to determine if an image is tagged as an animal or human
            if context["activity_category"] == CATEGORY_HUMAN:
                images = images.filter(Exists(BoundingBox.objects.is_person().filter(image=OuterRef("pk"))))
            else:
                images = images.filter(
                    Exists(BoundingBox.objects.is_nondomestic_species().filter(image=OuterRef("pk")))
                )

            images = images.order_by(
                "-upload__priority",
                "upload__camera_station",
                "trigger_timestamp",
                "num_activity_checked_by",
                "num_objects",
            )

            # Get the image stack based on stack size.
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

            # Serve the first image
            image_id = image_ids[0] if image_ids else None

        # If there is a valid image, add bounding box information
        if image_id:
            image = Image.objects.get(id=image_id)
            context["image"] = image
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes
        else:
            context["image"] = None
            context["bounding_boxes"] = []

        context["species_list"] = SpeciesName.objects.all()
        context["activity_list"] = ActivityType.objects.filter(category=context["category"])

        # Gather surrounding context images.
        CONTEXT_AMOUNT = 4

        lowerIndex = queue["index"] - CONTEXT_AMOUNT
        upperIndex = queue["index"] + CONTEXT_AMOUNT

        lowerIndex = 0 if (lowerIndex < 0) else lowerIndex
        upperIndex = len(queue["images"]) if (upperIndex > len(queue["images"])) else upperIndex

        context["context_images"] = [
            Image.objects.get(id=image_id) for image_id in queue["images"][lowerIndex:upperIndex]
        ]

        # Gather all annotations for bounding boxes.
        try:
            bboxes = BoundingBox.objects.filter(image=queue["images"][queue["index"]])
        except (ObjectDoesNotExist, IndexError):
            bboxes = []

        infoList = []

        for bbox in bboxes:
            categories = Category.objects.filter(bounding_box=bbox)
            species = Species.objects.filter(bounding_box=bbox)
            activities = Activity.objects.filter(bounding_box=bbox)

            infoList.append(BboxAnnotationInfo(bbox.id, categories, species, activities))

        context["bbox_all_annotations"] = infoList
        context["custom_annotations"] = custom_annotations

        return context


# TODO: Clean up this code
class MDAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # Get the image id
        image_id = request.POST.get("image_id")

        # Check if the image needs to be skipped
        if request.POST.get("skip"):
            skip = True
            initial_bboxes = []
            annotations = []
            logging.info(f"Bounding box annotations for image '{image_id}' was skipped by user - '{request.user.name}'")
            # Check if the image was tagged as needing staff review
            staff_review_needed = request.POST.get("staff_review_needed")
            staff_review_needed = bool(staff_review_needed and staff_review_needed == "true")
            # Process the annotations
            success = process_md_annotations(
                image_id, annotations, initial_bboxes, request.user, False, staff_review_needed, skip
            )
        else:
            # Get bounding box ids that were sent to infer deleted annotations
            initial_bboxes = request.POST.get("initial_bboxes")
            initial_bboxes = json.loads(initial_bboxes)

            # Get the annotation paylaod from the request and convert it to a dict
            annotations = request.POST.get("annotations")
            annotations = json.loads(annotations)

            # Check if the image was tagged as social media worthy
            social_media_worthy = request.POST.get("social_media_worthy")
            social_media_worthy = bool(social_media_worthy and social_media_worthy == "true")

            # Check if the image was tagged as needing staff review
            staff_review_needed = request.POST.get("staff_review_needed")
            staff_review_needed = bool(staff_review_needed and staff_review_needed == "true")

            logging.info(f"Processing bounding box annotations for image '{image_id}' by user - '{request.user.name}'")
            # Process the annotations
            success = process_md_annotations(
                image_id, annotations, initial_bboxes, request.user, social_media_worthy, staff_review_needed, False
            )

        # If success, update image index in the datastore
        if success:
            # Check if we're doing custom annotations
            custom_annotations = request.POST.get("custom_annotations", False) == "True"

            # Get the annotation queue cached in the datastore
            queue_name = OBJECTS_QUEUE_NAME
            if custom_annotations:
                queue_name = CUSTOM_PREFIX + queue_name
            queue = settings.DATASTORE_CLIENT.get(settings.DATASTORE_CLIENT.key(queue_name, str(request.user.id)))
            # Update the index
            queue["index"] += 1
            # Update the datastore
            settings.DATASTORE_CLIENT.put(queue)

        return JsonResponse({"success": success})


# TODO: Clean up this code
class SpeciesAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # Get the image id
        image_id = request.POST.get("image_id")

        skip = request.POST.get("skip") == "true"

        # Get bounding box ids that were sent to infer deleted annotations
        initial_bboxes = request.POST.get("initial_bboxes")
        initial_bboxes = json.loads(initial_bboxes)

        # Get the annotation paylaod from the request and convert it to a dict
        annotations = request.POST.get("annotations")
        annotations = json.loads(annotations)

        # Check if the image was tagged as social media worthy
        social_media_worthy = request.POST.get("social_media_worthy")
        social_media_worthy = True if social_media_worthy and social_media_worthy == "true" else False

        # Check if the image was tagged as needing staff review
        staff_review_needed = request.POST.get("staff_review_needed")
        staff_review_needed = bool(staff_review_needed and staff_review_needed == "true")

        # # Process the annotations
        # logging.info(f"Processing species for Image '{image_id}' by user - '{request.user.name}'")
        success = process_species_annotations(
            image_id, annotations, initial_bboxes, request.user, social_media_worthy, staff_review_needed, skip=skip
        )

        # If success, update image index in the datastore
        if success:
            # Check if we're doing custom annotations
            custom_annotations = request.POST.get("custom_annotations", False) == "True"

            # Get the annotation queue cached in the datastore
            queue_name = SPECIES_QUEUE_NAME
            if custom_annotations:
                queue_name = CUSTOM_PREFIX + queue_name
            queue = settings.DATASTORE_CLIENT.get(settings.DATASTORE_CLIENT.key(queue_name, str(request.user.id)))

            # Update the index
            queue["index"] += 1
            # Update the datastore
            settings.DATASTORE_CLIENT.put(queue)

        # # TODO: Send and render a meaningful response
        return JsonResponse({"success": success})


# TODO: Clean up this code
class ActivityAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # Get the image id
        image_id = request.POST.get("image_id")

        skip = request.POST.get("skip") == "true"

        activity_category = request.POST.get("activity_category")

        # Get bounding box ids that were sent to infer deleted annotations
        initial_bboxes = request.POST.get("initial_bboxes")
        initial_bboxes = json.loads(initial_bboxes)

        # Get the annotation paylaod from the request and convert it to a dict
        annotations = request.POST.get("annotations")
        annotations = json.loads(annotations)

        # # Process the annotations
        # logging.info(f"Processing activity for Image '{image_id}' by user - '{request.user.name}'")
        success = process_activity_annotations(image_id, annotations, initial_bboxes, request.user, skip=skip)

        # If success, update image index in the datastore
        if success:
            # Get the annotation queue cached in the datastore
            if activity_category == CATEGORY_HUMAN:
                queue_name = ACTIVITY_HUMAN_QUEUE_NAME
            else:
                queue_name = ACTIVITY_ANIMAL_QUEUE_NAME

            # Check if we're doing custom annotations
            custom_annotations = request.POST.get("custom_annotations", False) == "True"
            if custom_annotations:
                queue_name = CUSTOM_PREFIX + queue_name

            queue = settings.DATASTORE_CLIENT.get(settings.DATASTORE_CLIENT.key(queue_name, str(request.user.id)))

            # Update the index
            queue["index"] += 1
            # Update the datastore
            settings.DATASTORE_CLIENT.put(queue)

        # # TODO: Send and render a meaningful response
        return JsonResponse({"success": success})


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


class SaveRecentTagsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        annotations = request.POST.get("annotations")
        success = True

        try:
            request.session["recent_tags"] = annotations
        except BaseException as e:
            success = False

        return JsonResponse({"success": success})


class GetRecentTagsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = True

        try:
            recent_tags = self.request.session.get("recent_tags", [])
        except BaseException as e:
            success = False

        return JsonResponse({"success": success, "recent_tags": recent_tags})
