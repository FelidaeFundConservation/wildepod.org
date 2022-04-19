from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls.base import reverse_lazy
from django.views.generic import TemplateView


class ExploreDataView(LoginRequiredMixin, StaffuserRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "explore/main.html"


class ExportDataView(LoginRequiredMixin, StaffuserRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "explore/export_data.html"
    success_url = reverse_lazy("explore:data")
