from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from locations.models import CameraStation


class ExploreMapView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = CameraStation
    template_name = "explore/map.html"
