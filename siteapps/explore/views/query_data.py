# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Cast
from django.shortcuts import render
from django.views.generic import FormView

from images.models import Annotator, BoundingBox, Image, Species, SpeciesName
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 2


class QueryDataForm(forms.Form):

    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)
    
    microsites = forms.ModelMultipleChoiceField(queryset=MicroSite.objects.all(), required=False)
    
    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)
    
    species = forms.ModelMultipleChoiceField(
        queryset=SpeciesName.objects.filter(active=True).order_by('name'),
        required=False
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
                Column("species", css_class="form-group col-12"),
            ),
            Row(
                Column(Submit("submit", "Query", css_class="form-group btn-primary")),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True


class SearchDataView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "explore/query_data.html"
    form_class = QueryDataForm

    def post(self, request, *args, **kwargs):
        form = QueryDataForm(request.POST)
        results = {}

        if form.is_valid():
            # Use the form data to retrieve the filter conditions
            start_date = form.cleaned_data["start_date"]
            end_date = form.cleaned_data["end_date"]
            macrosites = form.cleaned_data["macrosites"]
            microsites = form.cleaned_data["microsites"]
            camera_stations = form.cleaned_data["camera_stations"]
            species = form.cleaned_data["species"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            if start_date:
                filterset["trigger_timestamp__gte"] = start_date
            if end_date:
                filterset["trigger_timestamp__lte"] = end_date
            if macrosites:
                filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
            if microsites:
                filterset["upload__camera_station__micro_site__in"] = microsites
            if camera_stations:
                filterset["upload__camera_station__in"] = camera_stations

            # Image has at least one bounding box tagged by MegaDetector above the predetermined threshold
            bounding_box_md_filter = BoundingBox.objects.filter(image=OuterRef("pk")).filter(
                confidence__gte=F("confidence_threshold")
            )

            queryset = Image.objects.filter(**filterset)
            
            # Apply species filter if specified
            if species:
                # Get species IDs from SpeciesName objects
                species_ids = [s.species_id for s in species if s.species_id]
                if species_ids:
                    # Filter images that have bounding boxes with these species
                    queryset = queryset.filter(
                        boundingbox__species__in=species_ids
                    ).distinct()
            
            aggregate_column_name = "upload__camera_station__micro_site__macro_site__name"
            queryset = (
                queryset.values(aggregate_column_name)
                .annotate(
                    name=F(aggregate_column_name),
                    total=Count("id"),
                    objects_detected_md=Count(Case(When(Exists(bounding_box_md_filter), then=1))),
                    category_complete=Sum(Cast("category_pipeline_complete", IntegerField())),
                    has_animals=Sum(Cast("has_animals", IntegerField())),
                    has_humans=Sum(Cast("has_humans", IntegerField())),
                    has_vehicles=Sum(Cast("has_vehicles", IntegerField())),
                    species_complete=Sum(Cast("species_pipeline_complete", IntegerField())),
                    has_wild_animals=Sum(Cast("has_wild_animals", IntegerField())),
                    activity_complete=Sum(Cast("activity_pipeline_complete", IntegerField())),
                )
                .order_by("-total")
            )

            results = list(queryset)
            logging.info(f"Querying data : {queryset.query}")

        return render(request, self.template_name, {"form": form, "results": results})
