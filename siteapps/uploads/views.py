import threading

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.base import TemplateView

from .forms import UploadFinalizeForm, UploadForm
from .models import Upload
from .utils import process_upload


class UploadCreateView(LoginRequiredMixin, CreateView):
    model = Upload
    form_class = UploadForm
    login_url = settings.LOGIN_URL
    template_name = "uploads/create.html"

    def get_success_url(self):
        return reverse("uploads:finalize", args=(self.object.id,))


class UploadListView(LoginRequiredMixin, ListView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "uploads/list.html"

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


class UploadFinalizeView(LoginRequiredMixin, UpdateView):
    model = Upload
    form_class = UploadFinalizeForm
    login_url = settings.LOGIN_URL
    template_name = "uploads/finalize.html"

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
        return reverse("uploads:list")


class UploadDetailView(LoginRequiredMixin, DetailView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "uploads/detail.html"

    def get_success_url(self):
        return reverse("uploads:detail")
