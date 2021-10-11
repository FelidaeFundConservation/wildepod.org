from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import TemplateView

from .models import Tag


class TagView(LoginRequiredMixin, TemplateView):
    # TODO: Use reverse with the url name instead of hardcoded url
    login_url = "/accounts/login"
    template_name = "tags/tag.html"
