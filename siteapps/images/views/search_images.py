from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery, Value
from django.shortcuts import render
from django.views.generic import FormView
from images.models import Annotator, BoundingBox, Image, Species
from locations.models import CameraStation, MacroSite

MAX_IMAGE_SEARCH_RESULTS = 100


class SearchImagesForm(forms.Form):

    volunteers = forms.ModelMultipleChoiceField(
        queryset=Annotator.objects.all(), widget=forms.SelectMultiple, required=False
    )

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    camera_timestamp_start = forms.DateTimeField(
        widget=forms.widgets.DateTimeInput(attrs={"type": "datetime-local"}), required=False
    )
    camera_timestamp_end = forms.DateTimeField(
        widget=forms.widgets.DateTimeInput(attrs={"type": "datetime-local"}), required=False
    )

    annotation_timestamp_start = forms.DateTimeField(
        widget=forms.widgets.DateTimeInput(attrs={"type": "datetime-local"}), required=False
    )
    annotation_timestamp_end = forms.DateTimeField(
        widget=forms.widgets.DateTimeInput(attrs={"type": "datetime-local"}), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                HTML("<h1>Search Images On Wildepod</h1><hr>"),
            ),
            Row(
                Column("volunteers", css_class="form-group col-12"),
            ),
            Row(
                Column("camera_timestamp_start", css_class="form-group col-md-6"),
                Column("camera_timestamp_end", css_class="form-group col-md-6"),
            ),
            Row(
                Column("annotation_timestamp_start", css_class="form-group col-md-6"),
                Column("annotation_timestamp_end", css_class="form-group col-md-6"),
            ),
            Row(
                Column("macrosites", css_class="form-group col-12"),
            ),
            Row(
                Column("camera_stations", css_class="form-group col-12"),
            ),
            Row(
                Column(Submit("submit", "Query Images", css_class="form-group btn-primary")),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True


class SearchImagesView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "images/search_images.html"
    form_class = SearchImagesForm

    def post(self, request, *args, **kwargs):
        form = SearchImagesForm(request.POST)
        results = {}

        if form.is_valid():
            # Use the form data to retrieve the filter conditions
            camera_timestamp_start = form.cleaned_data["camera_timestamp_start"]
            camera_timestamp_end = form.cleaned_data["camera_timestamp_end"]

            annotation_timestamp_start = form.cleaned_data["annotation_timestamp_start"]
            annotation_timestamp_end = form.cleaned_data["annotation_timestamp_end"]

            macrosites = form.cleaned_data["macrosites"]
            camera_stations = form.cleaned_data["camera_stations"]

            volunteers = form.cleaned_data["volunteers"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            if camera_timestamp_start:
                filterset["trigger_timestamp__gte"] = camera_timestamp_start
            if camera_timestamp_end:
                filterset["trigger_timestamp__lte"] = camera_timestamp_end
            if annotation_timestamp_start:
                filterset["trigger_timestamp__gte"] = annotation_timestamp_start
            if annotation_timestamp_end:
                filterset["trigger_timestamp__lte"] = annotation_timestamp_end
            if macrosites:
                filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
            if camera_stations:
                filterset["upload__camera_station__in"] = camera_stations

            volunteer_filter = None
            if volunteers:
                # Check if volunteer exists in any annotation type.
                volunteer_filter = (
                    Q(bbox_checked_by__in=volunteers)
                    | Q(species_checked_by__in=volunteers)
                    | Q(activity_checked_by__in=volunteers)
                )

            if volunteer_filter:
                query_result_count = Image.objects.annotated().filter(volunteer_filter, **filterset).count()
            else:
                query_result_count = Image.objects.annotated().filter(**filterset).count()

            # If query result amount exceeds limit, don't get results.
            if query_result_count <= MAX_IMAGE_SEARCH_RESULTS:
                if volunteer_filter:
                    queryset_all = Image.objects.annotated().filter(volunteer_filter, **filterset)
                else:
                    queryset_all = Image.objects.annotated().filter(**filterset)
                results = list(queryset_all)
            else:
                results = None

        return render(request, self.template_name, {"form": form, "results": results, "count": query_result_count})
