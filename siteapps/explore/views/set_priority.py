import logging

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, F, Q, Value
from django.shortcuts import render
from django.views.generic import FormView
from images.models import Image
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 2


class SetPriorityForm(forms.Form):
    start_date = forms.DateField(
        widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False
    )

    end_date = forms.DateField(
        widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False
    )

    macrosites = forms.ModelMultipleChoiceField(
        queryset=MacroSite.objects.all(), required=False
    )

    microsites = forms.ModelMultipleChoiceField(
        queryset=MicroSite.objects.all(), required=False
    )

    camera_stations = forms.ModelMultipleChoiceField(
        queryset=CameraStation.objects.all(), required=False
    )

    priority_choices = [
        ("One", "Low"),
        ("Two", "Medium"),
        ("Three", "High"),
    ]
    priority_by = forms.ChoiceField(
        choices=priority_choices, widget=forms.ChoiceField, initial="One"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("start_date", css_class="form-group col-md-6"),
                Column("end_date", css_class="form-group col-md-6"),
            ),
            Row(
                Column("macrosites", css_class="form-group col-12"),
            ),
            Row(
                Column("microsites", css_class="form-group col-12"),
            ),
            Row(
                Column("camera_stations", css_class="form-group col-12"),
            ),
            Row(
                Column(
                    Fieldset(
                        "", "priority_by", css_class="form-check form-check-inline"
                    ),
                    css_class="form-group col-12",
                )
            ),
            Row(
                Column(Submit("submit", "SUBMIT", css_class="form-group btn-primary")),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True


class SetPriorityView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "explore/set_priority.html"
    form_class = SetPriorityForm

    def post(self, request, *args, **kwargs):
        form = SetPriorityForm(request.POST)
        results = {}

        if form.is_valid():
            # Use the form data to retrieve the filter conditions
            start_date = form.cleaned_data["start_date"]
            end_date = form.cleaned_data["end_date"]
            macrosites = form.cleaned_data["macrosites"]
            microsites = form.cleaned_data["microsites"]
            camera_stations = form.cleaned_data["camera_stations"]
            priority_by = form.cleaned_data["priority_by"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            if start_date:
                filterset["trigger_timestamp__gte"] = start_date
            if end_date:
                filterset["trigger_timestamp__lte"] = end_date
            if macrosites:
                filterset[
                    "upload__camera_station__micro_site__macro_site__in"
                ] = macrosites
            if microsites:
                filterset["upload__camera_station__micro_site__in"] = microsites
            if camera_stations:
                filterset["upload__camera_station__in"] = camera_stations
            queryset = Image.objects.filter(**filterset)

            # Group the queryset based on the breakdown_by parameter
            # If there is no grouping use a dummy operator to aggregate all the images into a single group.
            aggregate_column_name = ""
            if breakdown_by == "split_none":
                queryset = queryset.annotate(dummy_group_by=Value(" "))
                aggregate_column_name = "dummy_group_by"
            elif breakdown_by == "split_macrosites":
                aggregate_column_name = (
                    "upload__camera_station__micro_site__macro_site__name"
                )
            elif breakdown_by == "split_microsites":
                aggregate_column_name = "upload__camera_station__micro_site__name"
            elif breakdown_by == "split_camera_stations":
                aggregate_column_name = "upload__camera_station__station_id"
            queryset = queryset.values(aggregate_column_name).annotate(
                name=F(aggregate_column_name)
            )

            # Finally, annotate the queryset with the counts of images in each category.
            # This will be applied to each group specified in the values() call above.
            queryset = queryset.annotate(
                all_images=Count("pk", distinct=True),
                md_processed=Count("pk", filter=Q(processed=True), distinct=True),
                md_objects_detected=Count(
                    "pk", filter=Q(boundingbox__gte=1), distinct=True
                ),
                bbox_checked=Count(
                    "pk",
                    filter=Q(bbox_checked_by__gte=MAX_VOTES_PER_IMAGE),
                    distinct=True,
                ),
                species_checked=Count(
                    "pk",
                    filter=Q(species_checked_by__gte=MAX_VOTES_PER_IMAGE),
                    distinct=True,
                ),
                activity_checked=Count(
                    "pk",
                    filter=Q(activity_checked_by__gte=MAX_VOTES_PER_IMAGE),
                    distinct=True,
                ),
            ).order_by("-all_images")
            results = queryset

            logging.info(f"Querying data : {queryset.query}")

        return render(request, self.template_name, {"form": form, "results": results})
