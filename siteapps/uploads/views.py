from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView

from .forms import UploadFinalizeForm, UploadForm
from .models import Upload


class UploadCreateView(LoginRequiredMixin, CreateView):
    # TODO: Use reverse with the url name instead of hardcoded url
    model = Upload
    form_class = UploadForm
    login_url = "/accounts/login"
    template_name = "uploads/upload.html"

    def get_success_url(self):
        return reverse("uploads:finalize", args=(self.object.id,))


class UploadListView(LoginRequiredMixin, ListView):
    # TODO: Use reverse with the url name instead of hardcoded url
    model = Upload
    login_url = "/accounts/login"
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
    # TODO: Use reverse with the url name instead of hardcoded url
    model = Upload
    form_class = UploadFinalizeForm
    login_url = "/accounts/login"
    template_name = "uploads/finalize.html"

    def get_success_url(self):
        return reverse("uploads:list")
