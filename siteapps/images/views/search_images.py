from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import (Count, Exists, F, OuterRef, Q, QuerySet,
                              Subquery, Value)
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import FormView
from images.models import (Activity, Annotator, BoundingBox, Category, Image,
                           Species)
from locations.models import CameraStation, MacroSite

MAX_IMAGE_SEARCH_RESULTS = 200


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
    staff_review_needed = forms.BooleanField(label="Flagged for Staff?", required=False)

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
                Column("staff_review_needed", css_class="form-group col-12"),
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

            staff_review_needed = form.cleaned_data["staff_review_needed"]

            # Apply the filters specified on the form on to the queryset
            filterset = {}
            compoundfilter = []

            if camera_timestamp_start:
                filterset["trigger_timestamp__gte"] = camera_timestamp_start
            if camera_timestamp_end:
                filterset["trigger_timestamp__lte"] = camera_timestamp_end
            if staff_review_needed:
                filterset["staff_review_needed"] = True

            """
            Logic to combine compound boundingbox filters.

            Filters by images with the existence of at least one category, species, or activity
            created by any specified volunteers within the given timestamp criteria.
            """

            q_filter_category = Q()
            q_filter_species = Q()
            q_filter_activity = Q()

            if volunteers:
                if not q_filter_category.children:
                    q_filter_category |= Q(boundingbox__category__created_by__in=volunteers)
                    q_filter_species |= Q(boundingbox__species__created_by__in=volunteers)
                    q_filter_activity |= Q(boundingbox__activity__created_by__in=volunteers)
                else:
                    q_filter_category &= Q(boundingbox__category__created_by__in=volunteers)
                    q_filter_species &= Q(boundingbox__species__created_by__in=volunteers)
                    q_filter_activity &= Q(boundingbox__activity__created_by__in=volunteers)

            if annotation_timestamp_start:
                if not q_filter_category.children:
                    q_filter_category |= Q(boundingbox__category__created__gte=annotation_timestamp_start)
                    q_filter_species |= Q(boundingbox__species__created__gte=annotation_timestamp_start)
                    q_filter_activity |= Q(boundingbox__activity__created__gte=annotation_timestamp_start)
                else:
                    q_filter_category &= Q(boundingbox__category__created__gte=annotation_timestamp_start)
                    q_filter_species &= Q(boundingbox__species__created__gte=annotation_timestamp_start)
                    q_filter_activity &= Q(boundingbox__activity__created__gte=annotation_timestamp_start)
            if annotation_timestamp_end:
                if not q_filter_category.children:
                    q_filter_category |= Q(boundingbox__category__created__lte=annotation_timestamp_end)
                    q_filter_species |= Q(boundingbox__species__created__lte=annotation_timestamp_end)
                    q_filter_activity |= Q(boundingbox__activity__created__lte=annotation_timestamp_end)
                else:
                    q_filter_category &= Q(boundingbox__category__created__lte=annotation_timestamp_end)
                    q_filter_species &= Q(boundingbox__species__created__lte=annotation_timestamp_end)
                    q_filter_activity &= Q(boundingbox__activity__created__lte=annotation_timestamp_end)

            compoundfilter.append(q_filter_category | q_filter_species | q_filter_activity)

            if macrosites:
                filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
            if camera_stations:
                filterset["upload__camera_station__in"] = camera_stations

            query_result_count = Image.objects.filter(*compoundfilter, **filterset).count()

            # If query result amount exceeds limit, don't get results.
            if query_result_count <= MAX_IMAGE_SEARCH_RESULTS:
                queryset_all = Image.objects.filter(*compoundfilter, **filterset)
                results = list(queryset_all)
            else:
                results = None

            # Get more detailed information from the results.
            annotations = {}

            if results:
                for image in results:
                    bboxes = BoundingBox.objects.filter(image=image)

                    category = []
                    species = []
                    activity = []

                    for bbox in bboxes:
                        category.append(Category.objects.filter(bounding_box=bbox))
                        species.append(Species.objects.filter(bounding_box=bbox))
                        activity.append(Activity.objects.filter(bounding_box=bbox))

                    annotations[image.id] = {"category": category, "species": species, "activity": activity}

        return render(
            request,
            self.template_name,
            {"form": form, "results": results, "count": query_result_count, "annotations": annotations},
        )
