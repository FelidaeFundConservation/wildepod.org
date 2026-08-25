# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
from datetime import timedelta

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery, Value
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import FormView
from images.models import (
    Activity,
    Annotator,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
    StaffReviewFlagReason,
    StaffReviewFlagSource,
)
from locations.models import CameraStation, MacroSite

MAX_IMAGE_SEARCH_RESULTS = 200

# How long a reviewer can be idle before the next search counts as a fresh review session.
# Searching repeatedly while working through a queue must not keep moving the NEW cutoff,
# or the badges would clear themselves out from under the person reading them.
#
# Long enough that a lunch break is still the same sitting -- at half an hour, coming back
# from lunch silently reset the cutoff and images that arrived that morning stopped being
# new before anyone had looked at them. Eight hours means "you were away long enough to have
# gone home", which is what a reviewer means by "last time I went through the queue".
REVIEW_SESSION_GAP = timedelta(hours=8)


def review_session_anchor(user):
    """Returns the cutoff for the NEW badge, rolling the review session over if it has lapsed.

    Images flagged after the returned time are new since this reviewer last sat down with the
    queue. Returns None when there is no previous session to compare against, which means no
    image is marked NEW.

    Has a side effect: starts a new review session (and saves the user) when more than
    REVIEW_SESSION_GAP has passed since the last search. Within a session the returned value
    does not move, so badges stay put while the queue is being worked.

    Arguments
    ---
        - user (users.models.User): The reviewer running the search.
    """
    now = timezone.now()

    if user.last_review_visit_at is None or now - user.last_review_visit_at > REVIEW_SESSION_GAP:
        user.previous_review_visit_at = user.last_review_visit_at
        user.last_review_visit_at = now
        user.save(update_fields=["previous_review_visit_at", "last_review_visit_at"])

    return user.previous_review_visit_at


def flagged_by_display(row):
    """Returns a display name for whoever flagged an image, or "" if no one did.

    Mirrors Annotator.__str__, but reads the joined columns already present on a .values()
    row so the results table costs no extra queries. Auto-flagged images have no annotator
    and come back blank rather than as a placeholder -- the Flags column already says they
    were auto-flagged, so a name here would be repeating it.

    Arguments
    ---
        - row (dict): One .values() row, carrying the flagged_by__* columns selected below.
    """
    if row.get("flagged_by__type") == "bot":
        return row.get("flagged_by__bot__name") or ""

    # User.name is optional, so fall back to the email, which is the login and always set.
    return row.get("flagged_by__human__name") or row.get("flagged_by__human__email") or ""


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Who the "Assign to expert" bulk action can hand work to. Rendered into the page
        # rather than fetched over AJAX: the list is short and changes rarely.
        context["experts"] = get_user_model().objects.filter(is_expert=True).order_by("name", "email")

        return context

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

        if date:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                filterset &= Q(trigger_timestamp__date=date)
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(boundingbox__species__created__date=date) | Q(boundingbox__species__modified__date=date)
        # Both ends inclusive. The field is labelled "End Of Date Range", which reads as "up to
        # and including this day" -- but this compared __lt, so a search for the 1st to the
        # 15th quietly returned the 1st to the 14th, and picking a single day returned nothing
        # at all. Comparing on __date means the whole of the end day is covered, rather than
        # only its midnight.
        if start_date and end_date:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                filterset &= Q(
                    trigger_timestamp__date__gte=start_date,
                    trigger_timestamp__date__lte=end_date,
                )
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(
                    boundingbox__species__created__date__gte=start_date,
                    boundingbox__species__created__date__lte=end_date,
                ) | Q(
                    boundingbox__species__modified__date__gte=start_date,
                    boundingbox__species__modified__date__lte=end_date,
                )

        if hour:
            if time_filter_type == TRIGGER_TIMESTAMP_TYPE:
                filterset &= Q(trigger_timestamp__hour=hour)
            elif time_filter_type == LAST_ANNOTATED_TYPE:
                filterset &= Q(boundingbox__species__created__hour=hour) | Q(boundingbox__species__modified__hour=hour)

        # Ticking a box means "show me these", so the three OR together -- ticking more widens
        # the results rather than narrowing them. An unticked box does not filter at all, so
        # match on the literal "true"; the string "false" is itself truthy.
        # Reviewed images are deliberately not a box here. These boxes OR together, so an
        # accidental tick silently widens the search to every image review has ever closed,
        # and the only sign is a bigger number. Resolved images are reachable through the
        # Reviewed button in the Filter row instead, which narrows what came back and is
        # undone by clicking it again.
        flags = Q()
        if staff_review_needed == "true":
            flags |= Q(staff_review_needed=True)
        if image_reported == "true":
            flags |= Q(image_reported=True)
        if social_media_worthy == "true":
            flags |= Q(social_media_worthy__gt=0)
        filterset &= flags
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

        results = (
            results.order_by("-modified")
            # How many annotators gave up on this image. Counted per pipeline and summed, the
            # same way auto_flag_for_staff() reads them; distinct=True keeps the three joins
            # from inflating each other's counts.
            .annotate(
                skip_count=Count("bbox_skipped_by", distinct=True)
                + Count("species_skipped_by", distinct=True)
                + Count("activity_skipped_by", distinct=True)
            )
            .values(
                "skip_count",
                "id",
                "dropbox_file_name",
                "upload__camera_station__micro_site__macro_site__name",
                "upload__camera_station__station_id",
                "thumbnail_gcloud_path",
                # Sorted on in the results table
                "trigger_timestamp",
                # Why each image matched, so the results double as a triage list
                "staff_review_needed",
                # Carries no flag of its own to show, so without a chip of its own a resolved
                # image is a row with an empty Flags column and no reason to be in the results
                "staff_reviewed_at",
                "image_reported",
                "social_media_worthy",
                "flag_reason",
                "flag_source",
                # Who flagged it, so staff can see and search on it in the results table.
                # Read as separate columns rather than through Annotator.__str__ to keep this
                # a single query -- see flagged_by_display() for how they are assembled.
                "flagged_by__type",
                "flagged_by__human__name",
                "flagged_by__human__email",
                "flagged_by__bot__name",
                # Compared against the review session anchor to mark rows NEW
                "flagged_at",
            )
            .distinct()
        )

        # Label the reason chip server-side so the wording stays tied to the model's choices
        # rather than being duplicated (and drifting) in the template's JavaScript.
        labels = {**dict(StaffReviewFlagReason.choices), **dict(StaffReviewFlagSource.choices)}
        rows = list(results)

        # Read once for the whole result set, so every row is judged against the same cutoff
        anchor = review_session_anchor(request.user)

        for row in rows:
            row["flag_label"] = labels.get(row["flag_reason"] or row["flag_source"], "")
            row["flagged_by_name"] = flagged_by_display(row)
            # Flags predating provenance have no flagged_at and are never new. Neither is
            # anything at all on a reviewer's first visit, when there is no anchor.
            row["is_new"] = bool(anchor and row["flagged_at"] and row["flagged_at"] > anchor)

        return JsonResponse({"results": rows})
