import datetime
import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Exists, OuterRef, Q
from django.http.response import JsonResponse
from django.views.generic.base import TemplateView, View
from images.models import ActivityType, Annotator, BoundingBox, Image, SpeciesName
from images.processors import process_activity_annotations, process_md_annotations, process_species_annotations

MAX_VOTES_PER_IMAGE = 4


# TODO: Clean up this code
# TODO: There are several common bits of code across the three annotation views and should be refactored
class AnnotateObjectsView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/objects.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Get the annotation queue cached in the datastore
        queue_key = settings.DATASTORE_CLIENT.key("AnnotateObjectsQueue", str(self.request.user.id))
        queue = settings.DATASTORE_CLIENT.get(queue_key)

        # If a valid object exists and if it is not expired and if the index points to a valid image, serve it
        if (
            queue
            and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
            and queue["index"] < len(queue["images"])
        ):
            # Get the image id
            image_id = queue["images"][queue["index"]]
        else:
            # First get an image stack
            images = (
                Image.objects.annotated()
                .filter(
                    # It must not be checked or skipped by the current annotator
                    ~Q(bbox_checked_by__in=[annotator]) & ~Q(bbox_skipped_by__in=[annotator]),
                    # There must be at least one or more "uncertain" bounding boxes.
                    # This will make sure that the images that need more votes are served first
                    Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
                .order_by("-upload__priority", "trigger_timestamp")
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
            bounding_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=image)
            context["bounding_boxes"] = bounding_boxes
        else:
            context["image"] = None
            context["bounding_boxes"] = []

        return context


# TODO: Clean up this code
class AnnotateSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/species.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Get the annotation queue cached in the datastore
        queue_key = settings.DATASTORE_CLIENT.key("AnnotateSpeciesQueue", str(self.request.user.id))
        queue = settings.DATASTORE_CLIENT.get(queue_key)

        # If a valid object exists and if it is not expired and if the index points to a valid image, serve it
        if (
            queue
            and datetime.datetime.fromisoformat(queue["expires_at"]) > datetime.datetime.now()
            and queue["index"] < len(queue["images"])
        ):
            # Get the image id
            image_id = queue["images"][queue["index"]]
        else:
            # Get images based on the following set of filters
            images = (
                Image.objects.annotated()
                .filter(
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
                    # Image must be marked as processed
                    processed=True,
                    num_species_checked_by__lt=MAX_VOTES_PER_IMAGE,
                )
                .order_by("-upload__priority", "num_species_checked_by", "trigger_timestamp", "num_objects")
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
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes
        else:
            context["image"] = None
            context["bounding_boxes"] = []

        context["species_list"] = SpeciesName.objects.all()

        return context


# TODO: Clean up this code
class AnnotateActivityView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/activity.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        # Get images based on the following set of filters
        images = (
            Image.objects.annotated()
            .filter(
                # It must not be checked or skipped by the current annotator
                ~Q(activity_checked_by__in=[annotator]) & ~Q(activity_skipped_by__in=[annotator]),
                # There must be at least one or more "valid" bounding boxes
                Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                # There must be no uncertain bounding boxes for the image
                ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                # TODO: The same issues with the species annotation filter might come up here too
                Exists(BoundingBox.objects.is_species_tagged().filter(image=OuterRef("pk"))),
                # Image must be marked as processed
                processed=True,
                num_activity_checked_by__lt=MAX_VOTES_PER_IMAGE,
            )
            .order_by("-upload__priority", "num_activity_checked_by", "trigger_timestamp", "num_objects")
        )

        # Serve the first image
        image = images.first()
        context["image"] = image

        # If there is a valid image, add bounding box information
        if image:
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes

        context["activity_list"] = ActivityType.objects.all()

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
            # Process the annotations
            success = process_md_annotations(image_id, annotations, initial_bboxes, request.user, skip)
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

            logging.info(f"Processing bounding box annotations for image '{image_id}' by user - '{request.user.name}'")
            # Process the annotations
            success = process_md_annotations(image_id, annotations, initial_bboxes, request.user, social_media_worthy)

        # If success, update image index in the datastore
        if success:
            # Get the queue entity
            queue = settings.DATASTORE_CLIENT.get(
                settings.DATASTORE_CLIENT.key("AnnotateObjectsQueue", str(request.user.id))
            )
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

        # # Process the annotations
        # logging.info(f"Processing species for Image '{image_id}' by user - '{request.user.name}'")
        success = process_species_annotations(image_id, annotations, initial_bboxes, request.user, skip=skip)

        # If success, update image index in the datastore
        if success:
            # Get the queue entity
            queue = settings.DATASTORE_CLIENT.get(
                settings.DATASTORE_CLIENT.key("AnnotateSpeciesQueue", str(request.user.id))
            )
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

        # Get bounding box ids that were sent to infer deleted annotations
        initial_bboxes = request.POST.get("initial_bboxes")
        initial_bboxes = json.loads(initial_bboxes)

        # Get the annotation paylaod from the request and convert it to a dict
        annotations = request.POST.get("annotations")
        annotations = json.loads(annotations)

        # # Process the annotations
        # logging.info(f"Processing activity for Image '{image_id}' by user - '{request.user.name}'")
        success = process_activity_annotations(image_id, annotations, initial_bboxes, request.user, skip=skip)

        # # TODO: Send and render a meaningful response
        return JsonResponse({"success": success})
