from datetime import timedelta

import pytz
from braces.views import StaffuserRequiredMixin
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.utils import timezone
from django.views.generic import ListView
from images.models import AnnotationCounter, Annotator, Image
from images.views import activity_pipeline_query, object_pipeline_query, species_pipeline_query

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
    ):
        self.name = name
        self.name_no_spaces = name_no_spaces

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


class TrackVolunteerEngagementView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "explore/track_volunteer_engagement.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Calculuate cutoff date for past week and month.
        pacific_timezone = pytz.timezone("America/Los_Angeles")
        now_pacific = timezone.now().astimezone(pacific_timezone)
        past_month_start_time = now_pacific - relativedelta(months=1)
        past_week_start_time = now_pacific - relativedelta(weeks=1)

        # Clear counters older than 1 month
        counters = AnnotationCounter.objects.filter(created__lt=past_month_start_time)
        if counters.exists():
            counters.delete()

        # Get daily annotation counts across all users
        daily_total_counts = []
        daily_category_counts = []
        daily_species_counts = []
        daily_activity_counts = []

        # Number of images annotated
        category_image_count = 0
        species_image_count = 0
        activity_image_count = 0

        # Get annotation counts for last 30 days
        for days in reversed(range(0, 30)):
            start = now_pacific - timedelta(days=days)
            start = timezone.make_aware(timezone.datetime(start.year, start.month, start.day))
            end = now_pacific - timedelta(days=days) + timedelta(days=1)
            end = timezone.make_aware(timezone.datetime(end.year, end.month, end.day))

            counters = AnnotationCounter.objects.filter(created__gte=start, created__lt=end)

            category_counters = counters.filter(annotation_type="category")
            category_counter_sum = category_counters.aggregate(Sum("annotation_count"))["annotation_count__sum"]
            category_count = category_counter_sum if category_counter_sum else 0
            category_image_count += category_counters.aggregate(Sum("image_count"))["image_count__sum"] or 0
            daily_category_counts.append(category_count)

            species_counters = counters.filter(annotation_type="species")
            species_counter_sum = species_counters.aggregate(Sum("annotation_count"))["annotation_count__sum"]
            species_count = species_counter_sum if species_counter_sum else 0
            species_image_count += species_counters.aggregate(Sum("image_count"))["image_count__sum"] or 0
            daily_species_counts.append(species_count)

            activity_counters = counters.filter(annotation_type="activity")
            activity_counter_sum = activity_counters.aggregate(Sum("annotation_count"))["annotation_count__sum"]
            activity_count = activity_counter_sum if activity_counter_sum else 0
            activity_image_count += activity_counters.aggregate(Sum("image_count"))["image_count__sum"] or 0
            daily_activity_counts.append(activity_count)

            daily_total_counts.append(category_count + species_count + activity_count)

        context["daily_category_counts"] = daily_category_counts
        context["daily_species_counts"] = daily_species_counts
        context["daily_activity_counts"] = daily_activity_counts
        context["daily_total_counts"] = daily_total_counts

        # Daily average
        context["daily_category_avg"] = round(sum(daily_category_counts) / len(daily_category_counts), 2)
        context["daily_species_avg"] = round(sum(daily_species_counts) / len(daily_species_counts), 2)
        context["daily_activity_avg"] = round(sum(daily_activity_counts) / len(daily_activity_counts), 2)
        context["daily_total_avg"] = round(sum(daily_total_counts) / len(daily_total_counts), 2)

        # Total pipeline eligible images
        images = Image.objects.all()
        context["category_pipeline_images"] = object_pipeline_query(images=images, annotator=None).count()
        context["species_pipeline_images"] = species_pipeline_query(images=images, annotator=None).count()
        context["activity_pipeline_images"] = (
            activity_pipeline_query(images=images, annotator=None, activity_category="animal").count()
            + activity_pipeline_query(images=images, annotator=None, activity_category="human").count()
        )

        # Images per day rate
        context["daily_category_img_avg"] = round((category_image_count / 30), 2)
        context["daily_species_img_avg"] = round((species_image_count / 30), 2)
        context["daily_activity_img_avg"] = round((activity_image_count / 30), 2)

        # Estimated time to finish all eligible images
        context["category_finish_time"] = min(
            round(context["category_pipeline_images"] / (context["daily_category_img_avg"] + 1)), 365
        )
        context["species_finish_time"] = min(
            round(context["species_pipeline_images"] / (context["daily_species_img_avg"] + 1)), 365
        )
        context["activity_finish_time"] = min(
            round(context["activity_pipeline_images"] / (context["daily_activity_img_avg"] + 1)), 365
        )

        # Only volunteers who annotated in the last month will be shown
        volunteers = list(
            Annotator.objects.filter(recent_annotations__created__gte=past_month_start_time, type="human").distinct()
        )
        volunteer_info = []

        for volunteer in volunteers:
            annotations_past_week_category = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="category", created__gte=past_week_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_week_species = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="species", created__gte=past_week_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_week_activity = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="activity", created__gte=past_week_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_week = (
                annotations_past_week_category + annotations_past_week_species + annotations_past_week_activity
            )

            annotations_past_month_category = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="category", created__gte=past_month_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_month_species = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="species", created__gte=past_month_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_month_activity = (
                AnnotationCounter.objects.filter(
                    annotator=volunteer, annotation_type="activity", created__gte=past_month_start_time
                ).aggregate(Sum("annotation_count"))["annotation_count__sum"]
                or 0
            )

            annotations_past_month = (
                annotations_past_month_category + annotations_past_month_species + annotations_past_month_activity
            )

            annotations_all_time_category = volunteer.total_category_annotations or 0
            annotations_all_time_species = volunteer.total_species_annotations or 0
            annotations_all_time_activity = volunteer.total_activity_annotations or 0
            annotations_all_time = (
                annotations_all_time_category + annotations_all_time_species + annotations_all_time_activity
            )

            volunteer_info.append(
                VolunteerEngagementInfo(
                    name=str(volunteer),
                    name_no_spaces=str(volunteer).replace(" ", ""),
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
                )
            )

            context["volunteer_info"] = volunteer_info

        return context
