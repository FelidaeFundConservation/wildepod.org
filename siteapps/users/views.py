from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views.generic import FormView, ListView, TemplateView, UpdateView

from .forms import RegisterVolunteerForm

User = get_user_model()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "users/profile.html"
    fields = ["name", "phone_number"]
    success_message = "Information successfully updated"

    def get_success_url(self):
        return reverse("users:profile")

    def get_object(self):
        return self.request.user


class VolunteerListView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "users/volunteers/list.html"


class VolunteerRegisterView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "users/volunteers/add.html"
    form_class = RegisterVolunteerForm

    def get_success_url(self):
        return reverse("users:volunteer_added")

    def form_valid(self, form):
        # Custom add that creates a temporary password for a user and sends an email
        clean_data = form.cleaned_data
        _ = User.objects.create_user(
            email=clean_data["email"],
            name=clean_data["name"],
            phone_number=clean_data["phone_number"],
            is_volunteer=True,
        )
        return super().form_valid(form)


class VolunteerRegisterSuccessView(LoginRequiredMixin, StaffuserRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "users/volunteers/added.html"
