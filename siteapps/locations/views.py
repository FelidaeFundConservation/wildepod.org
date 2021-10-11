from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views.generic import ListView, TemplateView

from .models import CameraTrap


class MapView(LoginRequiredMixin, ListView):
    # TODO: Use reverse with the url name instead of hardcoded url
    login_url = "/accounts/login"
    model = CameraTrap
    template_name = "locations/map.html"
