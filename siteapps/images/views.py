import json
import logging
import threading

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.http.response import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.base import TemplateView, View
from images.processors import process_md_annotations, process_species_annotations, process_upload

from .forms import UploadCompleteForm, UploadForm
from .models import Annotator, BoundingBox, Image, SpeciesName, Upload

# Pagination size for images displayed for the upload detail page
IMAGE_PAGINATION_LIMIT = 24


# This function goes over all uploads marked as completed but not yet processed and triggers a thread to process them
# Upload processing threads can get killed when GCP decides to kill an instance when it gets no active http requests
# TODO: Ideally, move this to a cloud run instead of a thread within app engine
def process_stuck_upload_threads():
    """Function to process all uploads marked as completed but not yet processed"""
    # First get all uploads that are already being processed by threads
    uploads_currently_being_processed = {
        thread.name.split("--")[-1] for thread in threading.enumerate() if "process_upload" in thread.name
    }
    logging.info(f"{len(uploads_currently_being_processed)} uploads currently being processed")
    pending_uploads = [
        upload
        for upload in Upload.objects.filter(upload_complete=True, processed=False)
        if str(upload.id) not in uploads_currently_being_processed
    ]
    logging.info(f"{len(pending_uploads)} uploads crashed without being fully processed")
    # For each completed upload that isn't processed
    for upload in pending_uploads:
        # Create a thread to process the upload
        thread = threading.Thread(target=process_upload, args=[upload.id])
        # Set the name of the thread to the upload id and the function
        # This will be used to deduplicate process-upload thread runs
        thread.name = f"process_upload--{upload.id}"
        # Move it to the background
        thread.setDaemon(True)
        # Start running the thread
        thread.start()


class UploadCreateView(LoginRequiredMixin, CreateView):
    model = Upload
    form_class = UploadForm
    login_url = settings.LOGIN_URL
    template_name = "images/upload/create.html"

    def get_success_url(self):
        return reverse("images:complete_upload", args=(self.object.id,))


class UploadListView(LoginRequiredMixin, ListView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/list.html"

    # Staff can access all uploads across all users.
    # Non-staff users can see only their uploads
    def get_queryset(self):
        if self.request.user.is_staff or self.request.user.is_superuser:
            return super().get_queryset()
        else:
            return super().get_queryset().filter(volunteer=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        if self.request.user.is_staff or self.request.user.is_superuser:
            context["num_pending"] = Upload.objects.filter(upload_complete=False).count()
            context["num_completed"] = Upload.objects.filter(upload_complete=True).count()
        else:
            context["num_pending"] = Upload.objects.filter(upload_complete=False, volunteer=self.request.user).count()
            context["num_completed"] = Upload.objects.filter(upload_complete=True, volunteer=self.request.user).count()
        return context


class UploadCompleteView(LoginRequiredMixin, UpdateView):
    model = Upload
    form_class = UploadCompleteForm
    login_url = settings.LOGIN_URL
    template_name = "images/upload/complete.html"

    # Override post method to trigger a cloud task to process the upload
    def post(self, request, *args, **kwargs):
        # Process upload only if "upload_complete" was checked in the form
        if request.POST.get("upload_complete"):
            logging.info(
                f"Upload '{self.get_object().id}' marked as complete by the {self.request.user.name}. Starting a thread to process the upload.."
            )
            # Create a thread to process the upload
            thread = threading.Thread(target=process_upload, args=[self.get_object().id])
            # Set the name of the thread to the upload id and the function
            # This will be used to deduplicate process-upload thread runs
            thread.name = f"process_upload--{self.get_object().id}"
            # Move it to the background
            thread.setDaemon(True)
            # Start running the thread
            thread.start()

        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("images:list_uploads")


class UploadDetailView(LoginRequiredMixin, DetailView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        # Get valid annotations for this image
        images = self.get_object().image_set.all()
        paginator = Paginator(images, IMAGE_PAGINATION_LIMIT)
        page_number = self.request.GET.get("page")
        paged_images = paginator.get_page(page_number)
        # TODO: Clean this up
        context["paged_images"] = paged_images
        context["paged_images_w_boxes"] = [
            [image_obj, BoundingBox.objects.valid().filter(image=image_obj)] for image_obj in paged_images
        ]

        return context


# TODO: Clean up this code
class UploadStatusView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        upload_ids = request.POST.get("upload_ids", "[]")
        upload_ids = json.loads(upload_ids)
        upload_statuses = {}
        for upload_id in upload_ids:
            try:
                upload = Upload.objects.get(id=upload_id)
                total_images = upload.image_set.count()
                processed_images = upload.image_set.filter(processed=True).count()
                upload_statuses[upload_id] = {
                    "valid": True,
                    "total_images": total_images,
                    "processed_images": processed_images,
                }
            except ObjectDoesNotExist:
                upload_statuses[upload_id] = {
                    "valid": False,
                    "total_images": 0,
                    "processed_images": 0,
                }
        return JsonResponse({"success": True, "upload_statuses": upload_statuses})


# TODO: This view is a hack to manually retrigger the processing of an upload
# Upload processing threads can get killed when GCP decides to kill and instance when it gets no active http requests
# Ideally, move this to a cloud run instead of a thread within app engine
class UploadResumeProcessingView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        logging.info("Manually triggered to process crashed uploads")
        # Trigger all uploads that are pending
        process_stuck_upload_threads()

        return JsonResponse({"success": True})


class ImageDetailView(LoginRequiredMixin, DetailView):
    model = Image
    login_url = settings.LOGIN_URL
    template_name = "images/image.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        try:
            context["next_image"] = self.get_object().get_previous_by_created()
        except ObjectDoesNotExist:
            pass
        try:
            context["previous_image"] = self.get_object().get_next_by_created()
        except ObjectDoesNotExist:
            pass
        # Get valid annotations for this image
        bounding_boxes = BoundingBox.objects.valid().filter(image=self.get_object())
        context["bounding_boxes"] = bounding_boxes

        return context


# TODO: Clean up this code
class AnnotateObjectsView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/objects.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        images = (
            Image.objects.annotated()
            .filter(
                ~Q(bbox_checked_by__in=[annotator]) & ~Q(bbox_skipped_by__in=[annotator]),
                processed=True,
                num_objects__gt=0,
            )
            .order_by("num_bbox_checked_by", "num_objects")
        )

        # Serve the first image
        image = images.first()
        context["image"] = image

        # If there is a valid image, add bounding box information
        if image:
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes

        return context


# TODO: Clean up this code
class AnnotateSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/annotate/species.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # First get the annotator object for the user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=self.request.user)

        images = (
            Image.objects.annotated()
            .filter(
                ~Q(species_checked_by__in=[annotator]) & ~Q(species_skipped_by__in=[annotator]),
                processed=True,
                num_objects__gt=0,
                num_bbox_checked_by=4,
            )
            .order_by("num_species_checked_by", "num_objects")
        )

        # Serve the first image
        image = images.first()
        context["image"] = image
        context["species_list"] = SpeciesName.objects.all()

        # If there is a valid image, add bounding box information
        if image:
            bounding_boxes = BoundingBox.objects.valid().filter(image=image)
            context["bounding_boxes"] = bounding_boxes

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
            process_md_annotations(image_id, annotations, initial_bboxes, request.user, skip)
        else:
            # Get bounding box ids that were sent to infer deleted annotations
            initial_bboxes = request.POST.get("initial_bboxes")
            initial_bboxes = json.loads(initial_bboxes)

            # Get the annotation paylaod from the request and convert it to a dict
            annotations = request.POST.get("annotations")
            annotations = json.loads(annotations)
            logging.info(f"Processing bounding box annotations for image '{image_id}' by user - '{request.user.name}'")
            # Process the annotations
            process_md_annotations(image_id, annotations, initial_bboxes, request.user)

        return JsonResponse({"success": True})


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

        # Process the annotations
        logging.info(f"Processing species for Image '{image_id}' by user - '{request.user.name}'")
        success = process_species_annotations(image_id, annotations, initial_bboxes, request.user, skip=skip)

        # TODO: Send and render a meaningful response
        return JsonResponse({"success": success})
