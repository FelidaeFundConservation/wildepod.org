import logging

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Value
from django.shortcuts import render
from django.views.generic import FormView
from images.models import Annotator, BoundingBox, Image, Species
from locations.models import CameraStation, MacroSite

MAX_VOTES_PER_IMAGE = 2


class QueryDataForm(forms.Form):

    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    radio_choices_breakdown = [
        ("split_none", "None"),
        ("split_macrosites", "Macrosites"),
        ("split_camera_stations", "Camera Stations"),
    ]
    breakdown_by = forms.ChoiceField(choices=radio_choices_breakdown, widget=forms.RadioSelect, initial="split_none")

    radio_choices_query = [
        ("query_blank_ready", "Images available for Blank pipeline"),
        ("query_blank_completed", "Blank pipeline completed images"),
        ("query_has_animal", "Images with animals"),
        ("query_has_human", "Images with humans"),
        ("query_has_vehicle", "Images with vehicles"),
        ("query_species_ready", "Images available for Species pipeline"),
        ("query_species_completed", "Species pipeline completed images"),
        ("query_activity_ready", "Images available for Activity pipeline"),
        ("query_activity_completed", "Activity pipeline completed images"),
    ]
    query_choice = forms.ChoiceField(choices=radio_choices_query, widget=forms.RadioSelect, initial="query_blank_ready")

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
                    Fieldset("", "breakdown_by", css_class="form-check form-check-inline"),
                    css_class="form-group col-12",
                )
            ),
            Row(
                Column(
                    Fieldset("", "query_choice", css_class="form-check form-check-inline"),
                    css_class="form-group col-12",
                )
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
            camera_stations = form.cleaned_data["camera_stations"]
            breakdown_by = form.cleaned_data["breakdown_by"]
            query_choice = form.cleaned_data["query_choice"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            if start_date:
                filterset["trigger_timestamp__gte"] = start_date
            if end_date:
                filterset["trigger_timestamp__lte"] = end_date
            if macrosites:
                filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
            if camera_stations:
                filterset["upload__camera_station__in"] = camera_stations

            queryset_all = Image.objects.annotated().filter(**filterset)

            # TODO: Share the queries between the annotation page views and this view so we only have a single definition for these queries.
            if query_choice == "query_blank_ready":
                queryset_all = queryset_all.filter(
                    # There must be at least one or more "uncertain" bounding boxes.
                    Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
            elif query_choice == "query_blank_completed":
                queryset_all = queryset_all.filter(
                    # There must be no "uncertain" bounding boxes
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
            elif query_choice == "query_has_animal":
                queryset_all = queryset_all.filter(
                    # There must be no "uncertain" bounding boxes
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must have an animal
                    Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
            elif query_choice == "query_has_human":
                queryset_all = queryset_all.filter(
                    # There must be no "uncertain" bounding boxes
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must have a human
                    Exists(BoundingBox.objects.is_person().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
            elif query_choice == "query_has_vehicle":
                queryset_all = queryset_all.filter(
                    # There must be no "uncertain" bounding boxes
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # Image must have a vehicle
                    Exists(BoundingBox.objects.is_vehicle().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed by MegaDetector
                    processed=True,
                    # Image must have at least one bounding box
                    num_objects__gt=0,
                )
            elif query_choice == "query_species_ready":
                queryset_all = queryset_all.filter(
                    # There must be at least one or more "valid" bounding boxes
                    Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                    # There must be no uncertain bounding boxes for the image
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # TODO: Fix the line below
                    # This is a quick and dirty hack to only ever show an image if there is at least
                    # one bounding box that has at least one category tagged as an animal linked to it
                    # It should work for most of the time but is not always accurate and will generate false positives
                    # Must be fixed
                    Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk"))),
                    # If a staff vote exists for the species, we'll no longer show it
                    ~Exists(
                        BoundingBox.objects.filter(
                            Exists(
                                Species.objects.filter(
                                    Exists(
                                        Annotator.objects.filter(
                                            accepted_species_annotation=OuterRef("pk"), human__is_staff=True
                                        )
                                    ),
                                    bounding_box=OuterRef("pk"),
                                )
                            ),
                            image=OuterRef("pk"),
                        )
                    ),
                    # Show image only if checked by fewer people
                    num_species_checked_by__lt=MAX_VOTES_PER_IMAGE,
                    # Image must be marked as processed
                    processed=True,
                )
            elif query_choice == "query_species_completed":
                queryset_all = queryset_all.filter(
                    # There must be at least one or more "valid" bounding boxes
                    Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                    # There must be no uncertain bounding boxes for the image
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # TODO: Fix the line below
                    # This is a quick and dirty hack to only ever show an image if there is at least
                    # one bounding box that has at least one category tagged as an animal linked to it
                    # It should work for most of the time but is not always accurate and will generate false positives
                    # Must be fixed
                    Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk"))),
                    # Either we have a staff vote OR more than or equal to minimum consensus threshold
                    Exists(
                        BoundingBox.objects.filter(
                            Exists(
                                Species.objects.filter(
                                    Exists(
                                        Annotator.objects.filter(
                                            accepted_species_annotation=OuterRef("pk"), human__is_staff=True
                                        )
                                    ),
                                    bounding_box=OuterRef("pk"),
                                )
                            ),
                            image=OuterRef("pk"),
                        )
                    )
                    | Q(num_species_checked_by__gte=MAX_VOTES_PER_IMAGE),
                    # Image must be marked as processed
                    processed=True,
                )
            elif query_choice == "query_activity_ready":
                queryset_all = queryset_all.filter(
                    # There must be at least one or more "valid" bounding boxes
                    Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                    # There must be no uncertain bounding boxes for the image
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # There must be non-domestic animals or humans
                    Exists(BoundingBox.objects.is_nondomestic_species().filter(image=OuterRef("pk")))
                    | Exists(BoundingBox.objects.is_person().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed
                    processed=True,
                    num_activity_checked_by__lt=MAX_VOTES_PER_IMAGE,
                )
            elif query_choice == "query_activity_completed":
                queryset_all = queryset_all.filter(
                    # There must be at least one or more "valid" bounding boxes
                    Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
                    # There must be no uncertain bounding boxes for the image
                    ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
                    # There must be non-domestic animals or humans
                    Exists(BoundingBox.objects.is_nondomestic_species().filter(image=OuterRef("pk")))
                    | Exists(BoundingBox.objects.is_person().filter(image=OuterRef("pk"))),
                    # Image must be marked as processed
                    processed=True,
                    num_activity_checked_by__gte=MAX_VOTES_PER_IMAGE,
                )

            if breakdown_by == "split_none":
                # If there is no grouping directly take the count() and pass it in the results.
                results = [{"name": " ", "all_images": queryset_all.count()}]
            else:
                # Group the queryset based on the breakdown_by parameter
                aggregate_column_name = ""
                if breakdown_by == "split_macrosites":
                    aggregate_column_name = "upload__camera_station__micro_site__macro_site__name"
                elif breakdown_by == "split_camera_stations":
                    aggregate_column_name = "upload__camera_station__station_id"
                queryset_all = (
                    queryset_all.values("id", aggregate_column_name)
                    .values(aggregate_column_name)
                    .annotate(name=F(aggregate_column_name))
                )

                # Finally, annotate the queryset with the counts of images in each category.
                # This will be applied to each group specified in the values() call above.
                queryset_all = queryset_all.annotate(
                    all_images=Count("pk", distinct=True),
                ).order_by("-all_images")

                results = list(queryset_all)
            logging.info(f"Querying data : {queryset_all.query}")

        return render(request, self.template_name, {"form": form, "results": results})
