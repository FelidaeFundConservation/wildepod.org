from datetime import timedelta

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
    annotations_all_time = None

    annotations_past_week_category = None
    annotations_past_week_species = None
    annotations_past_week_activity = None

    annotations_past_month_category = None
    annotations_past_month_species = None
    annotations_past_month_activity = None

    annotations_all_time_category = None
    annotations_all_time_species = None
    annotations_all_time_activity = None

    def __init__(
        self,
        name,
        name_no_spaces,
        last_login,
        annotations_past_week,
        annotations_past_month,
        annotations_all_time,
        annotations_past_week_category,
        annotations_past_week_species,
        annotations_past_week_activity,
        annotations_past_month_category,
        annotations_past_month_species,
        annotations_past_month_activity,
        annotations_all_time_category,
        annotations_all_time_species,
        annotations_all_time_activity,
        last_update_time,
    ):
        self.name = name
        self.name_no_spaces = name_no_spaces
        self.last_login = last_login

        self.annotations_past_week = annotations_past_week
        self.annotations_past_month = annotations_past_month
        self.annotations_all_time = annotations_all_time

        self.annotations_past_week_category = annotations_past_week_category
        self.annotations_past_week_species = annotations_past_week_species
        self.annotations_past_week_activity = annotations_past_week_activity

        self.annotations_past_month_category = annotations_past_month_category
        self.annotations_past_month_species = annotations_past_month_species
        self.annotations_past_month_activity = annotations_past_month_activity

        self.annotations_all_time_category = annotations_all_time_category
        self.annotations_all_time_species = annotations_all_time_species
        self.annotations_all_time_activity = annotations_all_time_activity

        self.last_update_time = last_update_time


class TrackVolunteerEngagementView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "explore/track_volunteer_engagement.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Calculuate cutoff date for past week and month.
        now = timezone.now()
        past_month_start_time = now - relativedelta(months=1)
        past_week_start_time = now - relativedelta(weeks=1)

        # Only include annotators who logged in recently
        volunteers = list(Annotator.objects.all())
        volunteer_info = []

        for volunteer in volunteers:
            try:
                last_login = volunteer.human.last_login
            except Exception as e:
                last_login = None

            volunteer = [volunteer]

            # Currently, there's no way to track what time an individual user's vote is made.
            # Instead, the creation of the annotation itself is used (regardless of who made the annotation).
            # Therefore, votes made more than 1 week/month after an annotation's initial creation might not be included in the count.
            past_week_q_filter = (
                Q(created_by__in=volunteer) | Q(accepted_by__in=volunteer) | Q(rejected_by__in=volunteer)
            ) & Q(created__gte=past_week_start_time)

            # Queries annotations between -1 month and -1 week
            past_month_partial_q_filter = (
                Q(created_by__in=volunteer) | Q(accepted_by__in=volunteer) | Q(rejected_by__in=volunteer)
            ) & Q(created__gte=past_month_start_time, created__lt=past_week_start_time)

            # Check last update time for all-time count
            last_update_time = volunteer[0].engagement_info_last_update
            new_update_time = timezone.now()

            # Queries annotations before -1 month
            all_time_partial_q_filter = (
                Q(created_by__in=volunteer) | Q(accepted_by__in=volunteer) | Q(rejected_by__in=volunteer)
            ) & Q(created__lt=past_month_start_time)

            # Get the annotation counts for category, species, and activity within timeframe.
            annotations_past_week_category = 0
            annotations_past_week_species = 0
            annotations_past_week_activity = 0
            annotations_past_week = 0
            annotations_past_month_category = 0
            annotations_past_month_species = 0
            annotations_past_month_activity = 0
            annotations_past_month = 0
            annotations_all_time_category = volunteer[0].total_category_annotations
            annotations_all_time_species = volunteer[0].total_species_annotations
            annotations_all_time_activity = volunteer[0].total_activity_annotations

            # Don't count weekly if not logged in within the last week
            if last_login and last_login > past_week_start_time:
                annotations_past_week_category = Category.objects.filter(past_week_q_filter).count()

                annotations_past_week_species = Species.objects.filter(past_week_q_filter).count()

                annotations_past_week_activity = Activity.objects.filter(past_week_q_filter).count()

                annotations_past_week = (
                    annotations_past_week_category + annotations_past_week_species + annotations_past_week_activity
                )

            # Don't count month if not logged in within the last month
            if last_login and last_login > past_month_start_time:
                annotations_past_month_category = (
                    annotations_past_week_category + Category.objects.filter(past_month_partial_q_filter).count()
                )

                annotations_past_month_species = (
                    annotations_past_week_species + Species.objects.filter(past_month_partial_q_filter).count()
                )

                annotations_past_month_activity = (
                    annotations_past_week_activity + Activity.objects.filter(past_month_partial_q_filter).count()
                )

                annotations_past_month = (
                    annotations_past_month_category + annotations_past_month_species + annotations_past_month_activity
                )

            # Check all-time again only after a certain period and if active
            if (last_update_time and (now - last_update_time > timedelta(minutes=30))) or (
                last_login
                and last_login < past_month_start_time
                and (annotations_all_time_category + annotations_all_time_species + annotations_all_time_activity == 0)
            ):
                annotations_all_time_category = (
                    annotations_past_month_category + Category.objects.filter(all_time_partial_q_filter).count()
                )
                volunteer[0].total_category_annotations = annotations_all_time_category

                annotations_all_time_species = (
                    annotations_past_month_species + Species.objects.filter(all_time_partial_q_filter).count()
                )
                volunteer[0].total_species_annotations = annotations_all_time_species

                annotations_all_time_activity = (
                    annotations_past_month_activity + Activity.objects.filter(all_time_partial_q_filter).count()
                )
                volunteer[0].total_activity_annotations = annotations_all_time_activity

                volunteer[0].engagement_info_last_update = new_update_time
                volunteer[0].save()
            else:
                pass

            annotations_all_time = (
                annotations_all_time_category + annotations_all_time_species + annotations_all_time_activity
            )

            volunteer_info.append(
                VolunteerEngagementInfo(
                    name=str(volunteer[0]),
                    name_no_spaces=str(volunteer[0]).replace(" ", ""),
                    last_login=last_login,
                    annotations_past_week=annotations_past_week,
                    annotations_past_month=annotations_past_month,
                    annotations_all_time=annotations_all_time,
                    annotations_past_week_category=annotations_past_week_category,
                    annotations_past_week_species=annotations_past_week_species,
                    annotations_past_week_activity=annotations_past_week_activity,
                    annotations_past_month_category=annotations_past_month_category,
                    annotations_past_month_species=annotations_past_month_species,
                    annotations_past_month_activity=annotations_past_month_activity,
                    annotations_all_time_category=annotations_all_time_category,
                    annotations_all_time_species=annotations_all_time_species,
                    annotations_all_time_activity=annotations_all_time_activity,
                    last_update_time=volunteer[0].engagement_info_last_update,
                )
            )

            # Sort by annotation counts in descending order.
            volunteer_info.sort(key=lambda volunteer_info: volunteer_info.annotations_all_time, reverse=True)

            context["volunteer_info"] = volunteer_info

        return context
