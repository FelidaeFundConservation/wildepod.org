from braces.views import StaffuserRequiredMixin
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Exists, F, Max, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import math
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView, UpdateView
from images.models import Activity, Annotator, BoundingBox, Category, Image, Species

User = get_user_model()


class VolunteerEngagementInfo:
    name = None
    name_no_spaces = None
    last_login = None
    annotations_past_week = None
    annotations_past_month = None

    annotations_past_week_category = None
    annotations_past_week_species = None
    annotations_past_week_activity = None

    annotations_past_month_category = None
    annotations_past_month_species = None
    annotations_past_month_activity = None

    def __init__(
        self,
        name,
        name_no_spaces,
        last_login,
        annotations_past_week,
        annotations_past_month,
        annotations_past_week_category,
        annotations_past_week_species,
        annotations_past_week_activity,
        annotations_past_month_category,
        annotations_past_month_species,
        annotations_past_month_activity,
    ):
        self.name = name
        self.name_no_spaces = name_no_spaces
        self.last_login = last_login
        self.annotations_past_week = annotations_past_week
        self.annotations_past_month = annotations_past_month

        self.annotations_past_week_category = annotations_past_week_category
        self.annotations_past_week_species = annotations_past_week_species
        self.annotations_past_week_activity = annotations_past_week_activity

        self.annotations_past_month_category = annotations_past_month_category
        self.annotations_past_month_species = annotations_past_month_species
        self.annotations_past_month_activity = annotations_past_month_activity


class TrackVolunteerEngagementView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "explore/track_volunteer_engagement.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        volunteers = list(Annotator.objects.all())
        volunteer_info = []

        # Calculuate cutoff date for past week and month.
        now = timezone.now()
        past_month_start_time = now - relativedelta(months=1)
        past_week_start_time = now - relativedelta(weeks=1)

        for volunteer in volunteers:
            volunteer = [volunteer]

            past_week_q_filter = (
                Q(created_by__in=volunteer, created__gte=past_week_start_time)
                | Q(accepted_by__in=volunteer, created__gte=past_week_start_time)
                | Q(rejected_by__in=volunteer, created__gte=past_week_start_time)
            )

            past_month_q_filter = (
                Q(created_by__in=volunteer, created__gte=past_month_start_time)
                | Q(accepted_by__in=volunteer, created__gte=past_month_start_time)
                | Q(rejected_by__in=volunteer, created__gte=past_month_start_time)
            )

            # Get the annotation counts for category, species, and activity.
            annotations_past_week_category = Category.objects.filter(past_week_q_filter).count()

            annotations_past_week_species = Species.objects.filter(past_week_q_filter).count()

            annotations_past_week_activity = Activity.objects.filter(past_week_q_filter).count()

            annotations_past_month_category = Category.objects.filter(past_month_q_filter).count()

            annotations_past_month_species = Species.objects.filter(past_month_q_filter).count()

            annotations_past_month_activity = Activity.objects.filter(past_month_q_filter).count()

            # Calculate total annotations across all types.
            annotations_past_month = (
                annotations_past_month_category + annotations_past_month_species + annotations_past_month_activity
            )

            annotations_past_week = (
                annotations_past_week_category + annotations_past_week_species + annotations_past_week_activity
            )

            try:
                last_login = volunteer[0].human.last_login
            except Exception:
                last_login = None

            volunteer_info.append(
                VolunteerEngagementInfo(
                    name=str(volunteer[0]),
                    name_no_spaces=str(volunteer[0]).replace(" ", ""),
                    last_login=last_login,
                    annotations_past_week=annotations_past_week,
                    annotations_past_month=annotations_past_month,
                    annotations_past_week_category=annotations_past_week_category,
                    annotations_past_week_species=annotations_past_week_species,
                    annotations_past_week_activity=annotations_past_week_activity,
                    annotations_past_month_category=annotations_past_month_category,
                    annotations_past_month_species=annotations_past_month_species,
                    annotations_past_month_activity=annotations_past_month_activity,
                )
            )

            # Sort by annotation counts in descending order.
            volunteer_info.sort(key=lambda volunteer_info: volunteer_info.annotations_past_month, reverse=True)

            context["volunteer_info"] = volunteer_info

        return context
