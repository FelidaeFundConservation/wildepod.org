from crispy_forms.bootstrap import StrictButton
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Column, Layout, Row, Submit
from django import forms
from locations.models import CameraStation, MacroSite

from .models import Upload


# User facing form to create an upload
class UploadForm(forms.ModelForm):
    date_retrieved = forms.SplitDateTimeField(
        widget=forms.widgets.SplitDateTimeWidget(date_attrs={"type": "date"}, time_attrs={"type": "time"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("camera_station", css_class="form-group"),
                css_class="form-row mb-3",
            ),
            Row(
                Column("volunteer", css_class="form-group col-md-4"),
                Column("date_retrieved", css_class="form-group col-md-4"),
                Column("last_action", css_class="form-group col-md-4"),
                css_class="form-row mb-3",
            ),
            Row(Column("comments", css_class="form-group"), css_class="form-row mb-3"),
            Row(
                Column(
                    Submit("submit", "Submit", css_class="btn-primary"),
                ),
                css_class="form-row text-center",
            ),
        )
        self.helper.form_show_errors = True

    class Meta:
        model = Upload
        date_retrieved = forms.SplitDateTimeField()
        fields = [
            "camera_station",
            "date_retrieved",
            "volunteer",
            "last_action",
            "comments",
        ]

        labels = {
            "date_retrieved": "Date & time retrieved",
        }


# User facing form to examine & mark an upload as completed
# after all pictures have been uploaded to Google Drive
class UploadCompleteForm(forms.ModelForm):
    date_retrieved = forms.SplitDateTimeField(
        widget=forms.widgets.SplitDateTimeWidget(date_attrs={"type": "date"}, time_attrs={"type": "time"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("upload_complete", css_class="form-group"),
                css_class="form-row lead",
            ),
            Row(
                Column(
                    Submit(
                        "submit",
                        "Submit",
                        css_class="btn-primary",
                        onclick=(
                            "return confirm('Once you mark this upload as complete, you cannot edit it further. Are you"
                            " sure about submitting?')"
                        ),
                    ),
                    StrictButton(
                        "Edit",
                        css_class="btn-primary",
                        aria_expanded="false",
                        aria_controls="edit-form",
                        data_bs_toggle="collapse",
                        data_bs_target="#edit-form",
                    ),
                ),
                css_class="form-row mb-3",
            ),
            Row(
                Row(
                    Column("camera_station", css_class="form-group"),
                    css_class="form-row my-3",
                ),
                Row(
                    Column("volunteer", css_class="form-group col-md-4"),
                    Column("date_retrieved", css_class="form-group col-md-4"),
                    Column("last_action", css_class="form-group col-md-4"),
                    css_class="form-row mb-3",
                ),
                Row(
                    Column("comments", css_class="form-group"),
                    css_class="form-row mb-3",
                ),
                css_class="form-row mb-3 collapse",
                css_id="edit-form",
            ),
        )
        self.helper.form_show_errors = True

    class Meta:
        model = Upload
        fields = [
            "camera_station",
            "date_retrieved",
            "volunteer",
            "last_action",
            "comments",
            "upload_complete",
        ]

        labels = {
            "date_retrieved": "Date & time retrieved",
        }


class AnnotationForm(forms.Form):
    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    macrosites = forms.ModelChoiceField(queryset=MacroSite.objects.all(), required=True)

    camera_stations = forms.ModelChoiceField(queryset=CameraStation.objects.all(), required=False)

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
                Column(Submit("submit", "Annotate", css_class="form-group btn-primary")),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True
