import logging
from datetime import datetime, timedelta

from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.views.generic import FormView, ListView, TemplateView, UpdateView, View
from images.models import Activity, Annotator, Category, Species

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

    # Gets the user annotation count data to show on the profile page.
    # Unrelated to update functions.
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        volunteer, created = Annotator.objects.get_or_create(type="human", human=self.request.user)

        if created:
            logging.info(f"Annotator object for user '{self.request.user}' successfully created")
        else:
            logging.info(f"Annotator object for user '{self.request.user}' already exists. Successfully retrieved.")

        user_annotations_q_filter = (
            Q(created_by__in=[volunteer]) | Q(accepted_by__in=[volunteer]) | Q(rejected_by__in=[volunteer])
        )

        context["user_category_annotation_count"] = Category.objects.filter(user_annotations_q_filter).count()
        context["user_species_annotation_count"] = Species.objects.filter(user_annotations_q_filter).count()
        context["user_activity_annotation_count"] = Activity.objects.filter(user_annotations_q_filter).count()

        context["user_total_annotation_count"] = (
            context["user_category_annotation_count"]
            + context["user_species_annotation_count"]
            + context["user_activity_annotation_count"]
        )

        return context


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


class VolunteerProfileView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "users/volunteers/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context[""]


class PrioritizeTaggingAnimalsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        new_time = datetime.now() + timedelta(hours=1)

        annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)

        annotator.prioritize_tagging_animals = new_time
        annotator.save()

        # Optionally, return a response
        return JsonResponse({"success": True})
