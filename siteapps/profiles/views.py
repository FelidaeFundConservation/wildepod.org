from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from .models import Profile


# TODO: Gate this to only staff members. Right now this is handled by simply not showing the url
class ProfileView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = Profile
    template_name = "profiles/profile.html"
