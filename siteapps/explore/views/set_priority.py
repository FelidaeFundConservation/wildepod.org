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
from images.models import Upload
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 2


class SetPriorityForm(forms.Form):
    start_date = forms.SplitDateTimeField(
        widget=forms.widgets.SplitDateTimeWidget(
            date_attrs={"type": "date"}, time_attrs={"type": "time"}
        ),
    )

    end_date = forms.SplitDateTimeField(
        widget=forms.widgets.SplitDateTimeWidget(
            date_attrs={"type": "date"}, time_attrs={"type": "time"}
        ),
    )

    macrosites = forms.ModelMultipleChoiceField(
        queryset=MacroSite.objects.all(), required=True
    )

    camera_stations = forms.ModelMultipleChoiceField(
        queryset=CameraStation.objects.all(), required=True
    )

    priority_choices = [
        ("1", "Low"),
        ("2", "Medium"),
        ("3", "High"),
    ]
    priority_by = forms.ChoiceField(
        choices=priority_choices, widget=forms.Select, initial="1"
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


class PriorityView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
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
            camera_stations = form.cleaned_data["camera_stations"]
            priority_by = form.cleaned_data["priority_by"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            if start_date:
                filterset["date_retrieved__gte"] = start_date
            if end_date:
                filterset["date_retrieved__lte"] = end_date
            if macrosites:
                filterset["camera_station__micro_site__macro_site__in"] = macrosites
            if camera_stations:
                filterset["camera_station__in"] = camera_stations
            Upload.objects.filter(**filterset).update(priority=priority_by)
            queryset = Upload.objects.filter(**filterset)
            print(queryset.values())
            results = queryset
            return render(
                request, self.template_name, {"form": form, "results": results}
            )
