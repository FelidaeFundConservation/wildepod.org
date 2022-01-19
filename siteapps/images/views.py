import json
import threading

import requests
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http.response import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.base import TemplateView, View

from .forms import UploadCompleteForm, UploadForm
from .models import Annotator, Image, Upload
from .utils import process_md_annotations, process_upload


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
            # Create a thread to process the upload
            thread = threading.Thread(target=process_upload, args=[self.get_object().id])
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


class ImageDetailView(LoginRequiredMixin, DetailView):
    model = Image
    login_url = settings.LOGIN_URL
    template_name = "images/image.html"


class MDAnnotationProcessorView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        # Get the image id
        image_id = request.POST.get("image_id")
        # Get bounding box ids that were sent to infer deleted annotations
        initial_bboxes = request.POST.get("initial_bboxes")
        initial_bboxes = json.loads(initial_bboxes)

        # Get the annotation paylaod from the request and convert it to a dict
        annotations = request.POST.get("annotations")
        annotations = json.loads(annotations)
        # Get the annotator object for the current user
        annotator, _ = Annotator.objects.get_or_create(type="human", human=request.user)
        # Process the annotations
        process_md_annotations(image_id, annotations, annotator, initial_bboxes)

        return JsonResponse({"success": True})
