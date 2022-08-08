from collections import Counter
import json
import logging
import threading

from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.http.response import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.base import TemplateView, View
from images.forms import UploadCompleteForm, UploadForm
from images.models import BoundingBox, Upload
from images.processors import process_upload

# Pagination size for images displayed for the upload detail page
IMAGE_PAGINATION_LIMIT = 24


# Views
# ------------------------------------------------------------------------------
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
            [image_obj, BoundingBox.objects.valid_or_uncertain().filter(image=image_obj)] for image_obj in paged_images
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
class UploadResumeProcessingView(StaffuserRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        logging.info("Manually triggered to process crashed uploads")
        # First get all uploads that are already being processed by threads
        uploads_currently_being_processed = {
            thread.name.split("--")[-1] for thread in threading.enumerate() if "process_upload" in thread.name
        }
        # TODO: Rewrite this
        # Only trigger this IF there are no uploads currently being processed
        if not uploads_currently_being_processed:
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
                # TODO: Fix this hack
                # Break out after the first one to reduce load temporarily
                break
        else:
            logging.info(f"{len(uploads_currently_being_processed)} uploads currently being processed")

        return JsonResponse({"success": True})


# TODO: This view is currently implemented purely to "test" the annotation functionality
# This should be moved into the explore app with arbitrary contraints to export annotations
class UploadExportView(LoginRequiredMixin, StaffuserRequiredMixin, DetailView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/export.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get all images
        annotated_images = []
        for image in self.get_object().image_set.all():
            uncertain_boxes = BoundingBox.objects.uncertain().filter(image=image)
            valid_or_uncertain_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=image)
            species_uncertain = [
                "uncertain" for bbox in valid_or_uncertain_boxes if not bbox.species_set.valid().exists()
            ]
            species_annotated_boxes = Counter(
                [
                    bbox.species_set.valid().first().name.name
                    for bbox in valid_or_uncertain_boxes
                    if bbox.species_set.valid().exists()
                ]
            )
            species_annotated_boxes_str = "<br/>".join(
                [f"{name} - {count}" for name, count in species_annotated_boxes.items()]
            )
            annotated_images.append(
                {
                    "image": image,
                    "status": "uncertain" if uncertain_boxes.count() > 0 or len(species_uncertain) > 0 else "certain",
                    "num_objects": valid_or_uncertain_boxes.count(),
                    "uncertain_boxes": uncertain_boxes,
                    "valid_or_uncertain_boxes": valid_or_uncertain_boxes,
                    "species_annotated_boxes": dict(species_annotated_boxes),
                    "species_annotated_boxes_str": species_annotated_boxes_str,
                }
            )
        context["annotated_images"] = annotated_images

        return context
