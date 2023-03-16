import logging

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Value
from django.shortcuts import render
from django.views.generic import FormView
from images.models import (ActivityType, Annotator, BoundingBox, Image,
                           SpeciesName)
from locations.models import CameraStation, MacroSite, MicroSite

MAX_VOTES_PER_IMAGE = 4


class QueryDataForm(forms.Form):

    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=False)

    microsites = forms.ModelMultipleChoiceField(queryset=MicroSite.objects.all(), required=False)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    radio_choices = [
        ("split_none", "None"),
        ("split_macrosites", "Macrosites"),
        ("split_microsites", "Microsites"),
        ("split_camera_stations", "Camera Stations"),
    ]
    breakdown_by = forms.ChoiceField(choices=radio_choices, widget=forms.RadioSelect, initial="split_none")

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
                    Fieldset("", "breakdown_by", css_class="form-check form-check-inline"),
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
            microsites = form.cleaned_data["microsites"]
            camera_stations = form.cleaned_data["camera_stations"]
            breakdown_by = form.cleaned_data["breakdown_by"]

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

            # The queries for each column,
            # 1. All Images
            queryset_all = Image.objects.annotated().filter(**filterset)
            # 2. Images available for Object annotation
            # queryset_objects = Image.objects.annotated().filter(
            #         # There must be at least one or more "uncertain" bounding boxes.
            #         # This will make sure that the images that need more votes are served first
            #         Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
            #         # Image must be marked as processed by MegaDetector
            #         processed=True,
            #         # Image must have at least one bounding box
            #         num_objects__gt=0,
            #     )
            # # 3. Images available for Species annotation
            # queryset_species = Image.objects.annotate(
            #     num_annotators=Subquery(
            #         Image.objects.filter(pk=OuterRef('pk'))
            #         .values('id')
            #         .annotate(count=Count('species_checked_by'))
            #         .values('count'))
            #     ).filter(
            #         # There must be at least one or more "valid" bounding boxes
            #         Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk"))),
            #         # There must be no uncertain bounding boxes for the image
            #         ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk"))),
            #         # TODO: Fix the line below
            #         # This is a quick and dirty hack to only ever show an image if there is at least
            #         # one bounding box that has at least one category tagged as an animal linked to it
            #         # It should work for most of the time but is not always accurate and will generate false positives
            #         # Must be fixed
            #         Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk"))),
            #         # Image must be marked as processed
            #         processed=True,
            #         num_annotators__lt=MAX_VOTES_PER_IMAGE,
            #     )

            # 4. Images available for Activity annotation


            # Group the queryset based on the breakdown_by parameter
            # If there is no grouping use a dummy operator to aggregate all the images into a single group.
            aggregate_column_name = ""
            if breakdown_by == "split_none":
                queryset_all = queryset_all.annotate(dummy_group_by=Value(" "))
                #queryset_objects = queryset_objects.annotate(dummy_group_by=Value(" "))
                #queryset_species = queryset_species.annotate(dummy_group_by=Value(" "))
                aggregate_column_name = "dummy_group_by"
            elif breakdown_by == "split_macrosites":
                aggregate_column_name = "upload__camera_station__micro_site__macro_site__name"
            elif breakdown_by == "split_microsites":
                aggregate_column_name = "upload__camera_station__micro_site__name"
            elif breakdown_by == "split_camera_stations":
                aggregate_column_name = "upload__camera_station__station_id"
            queryset_all = queryset_all.values(aggregate_column_name).annotate(name=F(aggregate_column_name))
            #queryset_objects = queryset_objects.values(aggregate_column_name).annotate(name=F(aggregate_column_name))
            #queryset_species = queryset_species.values(aggregate_column_name).annotate(name=F(aggregate_column_name))

            # Finally, annotate the queryset with the counts of images in each category.
            # This will be applied to each group specified in the values() call above.
            queryset_all = queryset_all.annotate(
                all_images=Count("pk", distinct=True),
                #md_processed=Count("pk", filter=Q(processed=True), distinct=True),
                #md_objects_detected=Count("pk", filter=Q(boundingbox__gte=1), distinct=True),
                blank_ready=Count("pk", filter=Q(processed=True)
                                    & Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk")))
                                    & Exists(BoundingBox.objects.filter(image=OuterRef("pk")))
                                    , distinct=True),
                blank_complete=Count("pk", filter=Q(processed=True)
                                    & ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk")))
                                    & Exists(BoundingBox.objects.filter(image=OuterRef("pk")))
                                    , distinct=True),
                species_ready=Count("pk", filter=Q(processed=True)
                                    & Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk")))
                                    & ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk")))
                                    & Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk")))
                                    & Q(id__in=Subquery(
                                            Image.objects.filter(pk=OuterRef('pk'))
                                            .annotate(num_annotators=Count('species_checked_by'))
                                            .filter(num_annotators__lt=MAX_VOTES_PER_IMAGE)
                                            .values('id')
                                        ))
                                    , distinct=True),
                species_complete=Count("pk", filter=Q(processed=True)
                                    & Exists(BoundingBox.objects.valid().filter(image=OuterRef("pk")))
                                    & ~Exists(BoundingBox.objects.uncertain().filter(image=OuterRef("pk")))
                                    & Exists(BoundingBox.objects.is_animal().filter(image=OuterRef("pk")))
                                    & Q(id__in=Subquery(
                                            Image.objects.filter(pk=OuterRef('pk'))
                                            .annotate(num_annotators=Count('species_checked_by'))
                                            .filter(num_annotators__gte=MAX_VOTES_PER_IMAGE)
                                            .values('id')
                                        ))
                                    , distinct=True),
            ).order_by("-all_images")

            # queryset_objects = queryset_objects.annotate(
            #     all_images=Count("pk", distinct=True)).order_by("-all_images")
            
            # queryset_species = queryset_species.annotate(
            #     all_images=Count("pk", distinct=True)).order_by("-all_images")
            
            # objects = {}
            # for obj in queryset_objects:
            #     objects[obj["name"]] = obj["all_images"]
            
            # species = {}
            # for obj in queryset_species:
            #     species[obj["name"]] = obj["all_images"]

            results = list(queryset_all)
            # for obj in results:
            #     obj["objects_pipeline"] = objects.get(obj["name"], 0)
            #     obj["species_pipeline"] = species.get(obj["name"], 0)

            print(results)
            logging.info(f"Querying data : {queryset_all.query}")

        return render(request, self.template_name, {"form": form, "results": results})
