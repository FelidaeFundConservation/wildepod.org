from braces.views import StaffuserRequiredMixin
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import FormView, ListView
from datetime import datetime, timedelta
from images.models import image, upload, annotation, annotator
from users.models import User


class VolunteerEngagementView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    model = User
    login_url = settings.LOGIN_URL

    weekly = datetime.today() - timedelta(days=7)

    template_name = "explore/volunteer_engagement.html"


from .volunteer_engagement import VolunteerEngagementView