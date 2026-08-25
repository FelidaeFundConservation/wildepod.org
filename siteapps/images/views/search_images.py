# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
from datetime import datetime, time, timedelta

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery, Value
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import FormView
from images.models import Activity, Annotator, BoundingBox, Category, Image, Species, SpeciesName
from locations.models import CameraStation, MacroSite

MAX_IMAGE_SEARCH_RESULTS = 200


class SearchImagesForm(forms.Form):

    volunteers = forms.ModelMultipleChoiceField(
        queryset=Annotator.objects.all(), widget=forms.SelectMultiple, required=False
    )

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    species = forms.ModelMultipleChoiceField(queryset=SpeciesName.objects.all(), required=False)

    species_ai = forms.ModelMultipleChoiceField(queryset=SpeciesName.objects.all(), label="Species AI", required=False)

    SEARCH_TYPE_CHOICES = [("OR", "OR"), ("AND", "AND")]
    search_type = forms.ChoiceField(choices=SEARCH_TYPE_CHOICES, label="Boolean Search Type")

    staff_review_needed = forms.BooleanField(label="Flagged for Staff?", required=False)
    image_reported = forms.BooleanField(label="Reported by User?", required=False)
    social_media_worthy = forms.BooleanField(label="Social media worthy?", required=False)

    TIME_SELECTION_CHOICES = [("LA", "Last Annotated"), ("TT", "Trigger Timestamp")]
    time_filter_type = forms.ChoiceField(choices=TIME_SELECTION_CHOICES, label="Time Filter Type")

    ANNO_SELECTION_CHOICES = [("SP", "Species")]
    annotation_type = forms.ChoiceField(choices=ANNO_SELECTION_CHOICES, label="Annotation Type")

    start_date = forms.DateField(
        label="Start Of Date Range", widget=forms.DateInput(attrs={"type": "date"}), required=False
    )
    end_date = forms.DateField(
        label="End Of Date Range", widget=forms.DateInput(attrs={"type": "date"}), required=False
    )

    date = forms.DateField(label="Exact Date", widget=forms.DateInput(attrs={"type": "month"}), required=False)
    hour = forms.IntegerField(min_value=0, max_value=23)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hour"].widget.attrs["readonly"] = True

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                HTML("<h1>Search Images On Wildepod</h1><hr>"),
            ),
            Row(
                Column("volunteers", css_class="form-group col-6"),
            ),
            Row(
                Column("species", css_class="form-group col-6"),
                Column("species_ai", css_class="form-group col-6"),
            ),
            Row(
                Column("macrosites", css_class="form-group col-6"),
                Column("camera_stations", css_class="form-group col-6"),
            ),
            Row(
                Column("search_type", css_class="form-group col-6"),
            ),
            Row(
                Column("staff_review_needed", css_class="form-group col-12"),
                Column("image_reported", css_class="form-group col-12"),
                Column("social_media_worthy", css_class="form-group col-12"),
            ),
            Row(HTML("<hr>")),
            Row(
                Column("time_filter_type", css_class="form-group col-12"),
            ),
            Row(
                Column("annotation_type", css_class="form-group col-12"),
            ),
            Row(
                Column("date", css_class="form-group col-4"),
            ),
            Row(
                Column("start_date", css_class="form-group col-4"),
                Column("end_date", css_class="form-group col-4"),
            ),
            Row(
                HTML(
                    "<div id='date-picker' class='form-group col-12 mb-4'>(Pick a date to show quick select buttons.)<br></div>"
                )
            ),
            Row(HTML("<hr>")),
            Row(
                Column(
                    Submit(
                        "submit",
                        "Select a time to view results.",
                        css_class="form-group btn-primary w-100 py-2 my-1 disabled",
                    )
                ),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True


class SearchImagesView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "images/search_images.html"
    form_class = SearchImagesForm

    def handle_no_permission(self, request=None):
        """Override to handle braces compatibility with newer Django versions."""
        # Django's AccessMixin.handle_no_permission() doesn't take request
        # but braces passes it, so we accept it optionally and ignore it
        from django.contrib.auth.mixins import AccessMixin

        return AccessMixin.handle_no_permission(self)

    def post(self, request, *args, **kwargs):
        TRIGGER_TIMESTAMP_TYPE = "TT"
        LAST_ANNOTATED_TYPE = "LA"

        # Use the form data to retrieve the filter conditions
        macrosites = request.POST.get("macrosites")
        if macrosites and not isinstance(macrosites, list):
            macrosites = json.loads(macrosites)

        camera_stations = request.POST.get("camera_stations")
        if camera_stations and not isinstance(camera_stations, list):
            camera_stations = json.loads(camera_stations)

        volunteers = request.POST.get("volunteers")
        if volunteers and not isinstance(volunteers, list):
            volunteers = json.loads(volunteers)

        species = request.POST.get("species")
        if species and not isinstance(species, list):
            species = json.loads(species)

        species_ai = request.POST.get("species_ai")
        if species_ai and not isinstance(species_ai, list):
            species_ai = json.loads(species_ai)

        search_type = request.POST.get("search_type")
        if search_type and not isinstance(search_type, list):
            search_type = json.loads(search_type)

        date = request.POST.get("date")

        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")

        hour = request.POST.get("hour")

        staff_review_needed = request.POST.get("staff_review_needed")
        image_reported = request.POST.get("image_reported")
        social_media_worthy = request.POST.get("social_media_worthy")

        time_filter_type = request.POST.get("time_filter_type")

        # Apply filters conditionally
        filterset = Q()

        # Use explicit local-time datetime windows for trigger timestamp filters.
        # This avoids UTC/local date boundary mismatches around midnight.
        local_tz = timezone.get_current_timezone()

        if date:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                parsed_date = datetime.fromisoformat(str(date)).date()
                start_dt = timezone.make_aware(datetime.combine(parsed_date, time.min), local_tz)
                end_dt = start_dt + timedelta(days=1)
                filterset &= Q(trigger_timestamp__gte=start_dt, trigger_timestamp__lt=end_dt)
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(boundingbox__species__created__date=date) | Q(boundingbox__species__modified__date=date)
        if start_date and end_date:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                parsed_start = datetime.fromisoformat(str(start_date)).date()
                parsed_end = datetime.fromisoformat(str(end_date)).date()
                start_dt = timezone.make_aware(datetime.combine(parsed_start, time.min), local_tz)
                end_dt = timezone.make_aware(datetime.combine(parsed_end, time.min), local_tz)
                filterset &= Q(
                    trigger_timestamp__gte=start_dt,
                    trigger_timestamp__lt=end_dt,
                )
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(
                    boundingbox__species__created__date__gte=start_date,
                    boundingbox__species__created__date__lt=end_date,
                ) | Q(
                    boundingbox__species__modified__date__gte=start_date,
                    boundingbox__species__modified__date__lt=end_date,
                )

        if hour:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                filterset &= Q(trigger_timestamp__hour=hour)
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(boundingbox__species__created__hour=hour) | Q(boundingbox__species__modified__hour=hour)

        if staff_review_needed:
            staff_review_needed = json.loads(staff_review_needed)
            filterset &= Q(staff_review_needed=staff_review_needed)
        if image_reported:
            image_reported = json.loads(image_reported)
            filterset &= Q(image_reported=image_reported)
        if social_media_worthy:
            filterset &= Q(social_media_worthy__gt=0)
        if len(volunteers) > 0:
            filterset &= (
                Q(boundingbox__species__created_by__id__in=volunteers)
                | Q(boundingbox__species__accepted_by__id__in=volunteers)
                | Q(boundingbox__species__rejected_by__id__in=volunteers)
            )
        if len(species) > 0 and search_type == "OR":
            filterset &= Q(boundingbox__species__name__in=species)
        if len(species_ai) > 0:
            # The Search form returns a list of Species ids while the ai_detections field contains the
            # species names as a list in string format.
            # Q expressions can't compare both sets directly, so we generate a Q expression for each species and combine them.
            species_ai_filter = Q()
            for id in species_ai:
                name = SpeciesName.objects.get(id=id).name
                species_ai_filter |= Q(species_ai_detections__icontains=name)
            filterset &= species_ai_filter
        if len(macrosites) > 0:
            filterset &= Q(upload__camera_station__micro_site__macro_site__in=macrosites)
        if len(camera_stations) > 0:
            filterset &= Q(upload__camera_station__in=camera_stations)

        # Query Images based on the filter criteria
        results = Image.objects.filter(filterset).distinct()

        # Apply AND filter method
        if search_type == "AND":
            for sp_name in species:
                results = results.filter(
                    Exists(BoundingBox.objects.filter(species__name=sp_name, image=OuterRef("pk")))
                )

        if len(results) > 0:
            results = (
                results.order_by("-modified")
                .values(
                    "id",
                    "dropbox_file_name",
                    "upload__camera_station__micro_site__macro_site__name",
                    "upload__camera_station__station_id",
                    "thumbnail_gcloud_path",
                )
                .distinct()
            )

        return JsonResponse({"results": list(results)})
