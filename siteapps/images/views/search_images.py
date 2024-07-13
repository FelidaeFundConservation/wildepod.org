import json

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
from images.models import Activity, Annotator, BoundingBox, Category, Image, Species
from locations.models import CameraStation, MacroSite

MAX_IMAGE_SEARCH_RESULTS = 200


class SearchImagesForm(forms.Form):

    volunteers = forms.ModelMultipleChoiceField(
        queryset=Annotator.objects.all(), widget=forms.SelectMultiple, required=False
    )

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    staff_review_needed = forms.BooleanField(label="Flagged for Staff?", required=False)

    SELECTION_CHOICES = [("SP", "Species"), ("ACT", "Activity")]
    annotation_type = forms.ChoiceField(choices=SELECTION_CHOICES, label="Annotation Type")

    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
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
                Column("volunteers", css_class="form-group col-12"),
            ),
            Row(
                Column("macrosites", css_class="form-group col-6"),
                Column("camera_stations", css_class="form-group col-6"),
            ),
            Row(
                Column("staff_review_needed", css_class="form-group col-12"),
            ),
            Row(HTML("<hr>")),
            Row(
                Column("annotation_type", css_class="form-group col-12"),
            ),
            Row(
                Column("date", css_class="form-group col-4"),
            ),
            Row(
                HTML(
                    "<div id='date-picker' class='form-group col-12 mb-4'>(Pick a date to see annotation distribution.)<br></div>"
                )
            ),
            Row(
                Column("hour", css_class="form-group col-4"),
            ),
            Row(HTML("<div id='time-picker' class='form-group col-12 mb-2'></div>")),
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

    def post(self, request, *args, **kwargs):
        SPECIES_ANNO_TYPE = "SP"
        ACTIVITY_ANNO_TYPE = "ACT"

        # Use the form data to retrieve the filter conditions
        macrosites = request.POST.get("macrosites")
        if macrosites and type(macrosites) != list:
            macrosites = json.loads(macrosites)

        camera_stations = request.POST.get("camera_stations")
        if camera_stations and type(camera_stations) != list:
            camera_stations = json.loads(camera_stations)

        volunteers = request.POST.get("volunteers")
        if volunteers and type(volunteers) != list:
            volunteers = json.loads(volunteers)

        date = request.POST.get("date")
        hour = request.POST.get("hour")

        staff_review_needed = request.POST.get("staff_review_needed")

        annotation_type = request.POST.get("annotation_type")

        # Apply filters conditionally
        filterset = Q()

        if date:
            filterset &= Q(created__date=date) | Q(modified__date=date)
        if hour:
            filterset &= Q(created__hour=hour) | Q(modified__hour=hour)
        if staff_review_needed:
            staff_review_needed = json.loads(staff_review_needed)
            filterset &= Q(bounding_box__image__staff_review_needed=staff_review_needed)
        if len(volunteers) > 0:
            filterset &= (
                Q(created_by__id__in=volunteers) | Q(accepted_by__id__in=volunteers) | Q(rejected_by__id__in=volunteers)
            )
        if len(macrosites) > 0:
            filterset &= Q(bounding_box__image__upload__camera_station__micro_site__macro_site__in=macrosites)
        if len(camera_stations) > 0:
            filterset &= Q(bounding_box__image__upload__camera_station__in=camera_stations)

        # Query annotation results
        results = []

        if annotation_type == SPECIES_ANNO_TYPE:
            results = Species.objects.filter(filterset)
        elif annotation_type == ACTIVITY_ANNO_TYPE:
            results = Activity.objects.filter(filterset)

        if len(results) > 0:
            results = results.order_by("-modified").values(
                "bounding_box__image__id",
                "bounding_box__image__upload__camera_station__micro_site__macro_site__name",
                "bounding_box__image__upload__camera_station__station_id",
                "modified",
                "name__name",
                "bounding_box__image__thumbnail_gcloud_path",
            )

        return JsonResponse({"results": list(results)})
