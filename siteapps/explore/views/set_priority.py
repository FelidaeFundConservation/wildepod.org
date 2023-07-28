from datetime import timedelta

from braces.views import StaffuserRequiredMixin
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Column, Fieldset, Layout, Row, Submit
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import serializers
from django.db.models import Count, F, Q, Value
from django.shortcuts import redirect, render
from django.views.generic import FormView
from images.models import Upload
from locations.models import CameraStation, MacroSite
from model_utils.managers import ObjectDoesNotExist


class SetPriorityForm(forms.Form):
    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    macrosites = forms.ModelMultipleChoiceField(queryset=MacroSite.objects.all(), required=True)

    camera_stations = forms.ModelMultipleChoiceField(queryset=CameraStation.objects.all(), required=False)

    priority_choices = Upload._meta.get_field("priority").choices
    priority_by = forms.ChoiceField(
        label="Set Priority To",
        choices=priority_choices,
        widget=forms.Select,
        initial="1",
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
                    Fieldset("", "priority_by", css_class="form-check form-check-inline"),
                    css_class="form-group col-12",
                )
            ),
            Row(
                Column(Submit("submit", "Submit", css_class="form-group btn-primary")),
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

        if form.is_valid():
            # Use the form data to retrieve the filter conditions
            start_date = form.cleaned_data["start_date"]
            end_date = form.cleaned_data["end_date"]
            macrosites = form.cleaned_data["macrosites"]
            camera_stations = form.cleaned_data["camera_stations"]
            priority_by = form.cleaned_data["priority_by"]

            filterset = {}
            if start_date:
                filterset["images__trigger_timestamp__gte"] = start_date
            if end_date:
                # to make the end_date inclusive as its conflicting because of datetimefield and datefield comparison
                end_date_inclusive = end_date + timedelta(days=1) - timedelta(seconds=1)
                filterset["images__trigger_timestamp__lte"] = end_date_inclusive
            if macrosites:
                filterset["camera_station__micro_site__macro_site__in"] = macrosites
            if camera_stations:
                filterset["camera_station__in"] = camera_stations
            search_set = Upload.objects.filter(**filterset).distinct()

            num_records_to_update = search_set.count()
            num_records_to_downgrade = None
            new_priority_display = form.fields["priority_by"].choices[int(priority_by) - 1][1]

            # Get existing Highest priority sets to replace.
            downgrade_set = None
            downgrade_sets_image_count = None

            if priority_by == "4":
                downgrade_set = Upload.objects.filter(priority=priority_by)
                num_records_to_downgrade = Upload.objects.filter(priority=priority_by).count()

            if num_records_to_update == 0:
                message = "No records found matching the search criteria."
                messages.info(request, message)
                return redirect("explore:set_priority")
            else:
                total_image_count = Upload.objects.filter(**filterset).aggregate(total_images=Count("images"))[
                    "total_images"
                ]

                # Preview sets to downgrade if they exist.
                try:
                    downgrade_sets_image_count = Upload.objects.filter(priority=4).aggregate(
                        total_downgrade_images=Count("images")
                    )["total_downgrade_images"]

                    downgrade_list = serializers.serialize("json", downgrade_set)
                    request.session["downgrade_list"] = downgrade_list
                except BaseException:
                    pass

                message = "Are you sure you want to continue?"
                # to serialize the model
                model_list = serializers.serialize("json", search_set)

                # saving serialized model and priority value
                request.session["priority_form_data"] = model_list
                request.session["priority_val"] = priority_by

                return render(
                    request,
                    "explore/set_priority_confirm.html",
                    {
                        "message": message,
                        "search_set": search_set,
                        "downgrade_set": downgrade_set,
                        "new_priority": priority_by,
                        "new_priority_display": new_priority_display,
                        "num_records_to_downgrade": num_records_to_downgrade,
                        "num_records_to_update": num_records_to_update,
                        "update_sets_image_count": total_image_count,
                        "downgrade_sets_image_count": downgrade_sets_image_count,
                    },
                )


class ConfirmUpdateView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "explore/set_priority_confirm.html"

    def post(self, request, *args, **kwargs):
        model_data = self.request.session.pop("priority_form_data")
        priority_val = self.request.session.pop("priority_val")
        count = 0

        # Push down previous Highest priority sets if setting new ones.
        if priority_val == "4":
            downgrade_list = self.request.session.pop("downgrade_list")

            for obj in serializers.deserialize("json", downgrade_list):
                obj.object.priority = "3"
                obj.save()
                count += 1

        for obj in serializers.deserialize("json", model_data):
            obj.object.priority = priority_val
            obj.save()
            count += 1

        message = f"{count} Upload Sets updated."
        messages.info(request, message)
        return redirect("explore:set_priority")
