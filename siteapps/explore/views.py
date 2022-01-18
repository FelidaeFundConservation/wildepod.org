from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, TemplateView
from locations.models import CameraStation


class ExploreHomeView(LoginRequiredMixin, TemplateView):
    template_name = "explore/main.html"


# TODO: Gate this to only staff members. Right now this is handled by simply not showing the url
class ExploreMapView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = CameraStation
    template_name = "explore/map.html"
