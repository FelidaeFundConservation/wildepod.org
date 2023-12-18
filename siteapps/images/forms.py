import calendar
from datetime import datetime

from crispy_forms.bootstrap import StrictButton
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Button, Column, Layout, Row, Submit
from django import forms
from locations.models import CameraStation, MacroSite

from .models import TimeCorrection, Upload


# User facing form to create an upload
class UploadForm(forms.ModelForm):
    date_retrieved = forms.SplitDateTimeField(
        widget=forms.widgets.SplitDateTimeWidget(date_attrs={"type": "date"}, time_attrs={"type": "time"}),
    )

    time_correction_years = forms.IntegerField(
        initial=0, required=False, help_text="Make sure these values are correct."
    )
    time_correction_months = forms.IntegerField(initial=0, required=False)
    time_correction_days = forms.IntegerField(initial=0, required=False)
    time_correction_hours = forms.IntegerField(initial=0, required=False)
    time_correction_minutes = forms.IntegerField(initial=0, required=False)

    start_date = forms.DateTimeField(
        widget=forms.widgets.TextInput(attrs={"type": "datetime-local"}),
        required=False,
    )

    end_date = forms.DateTimeField(
        widget=forms.widgets.TextInput(attrs={"type": "datetime-local"}),
        required=False,
    )

    daylight_savings_correction = forms.CharField(
        widget=forms.TextInput(),
        required=False,
        help_text="If there was a daylight savings shift, specify the month the shift occurred (March or November)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                HTML("<h5>Information</h5>"),
                HTML("<text class='small'>Enter metadata for the upload set.</text>"),
                css_class="form-row mb-4 px-3",
            ),
            Row(
                Column("camera_station", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column("volunteer", css_class="form-group col-md-4"),
                Column("date_retrieved", css_class="form-group col-md-4"),
                Column("last_action", css_class="form-group col-md-4"),
                css_class="form-row mb-3 px-3",
            ),
            Row(Column("comments", css_class="form-group"), css_class="form-row mb-3 px-3"),
            Row(
                HTML("<hr>"),
                HTML("<h5>Time Errors</h5>"),
                HTML(
                    "<text class='small'>If the camera's image timestamps are off, enter the adjustments needed to correct them. Don't enter if there's no time errors.</text>"
                ),
                HTML(
                    "<text>If there is an error, <b>only choose 1 correction type (daylight savings or time shift).</b></text>"
                ),
                css_class="form-row mb-4 px-3",
            ),
            Row(
                Column("time_correction_years", css_class="form-group"),
                Column("time_correction_months", css_class="form-group"),
                Column("time_correction_days", css_class="form-group"),
                Column("time_correction_hours", css_class="form-group"),
                Column("time_correction_minutes", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column("start_date", css_class="form-group"),
                Column("end_date", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column("daylight_savings_correction", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column(
                    Submit("submit", "Create Upload", css_class="btn-primary"),
                ),
                css_class="form-row text-center mb-3",
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

    def clean_daylight_savings_correction(self):
        date = self.cleaned_data.get("daylight_savings_correction")

        if date and date != "":
            month, year = date.split("-")

            date_str = f"{year}-{month}-{get_daylight_savings_date(month, year).day:02d}"
        else:
            date_str = None

        return date_str


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

    criteria = [
        ("species", "Annotate Species"),
        ("human", "Annotate Human Activity"),
        ("animal", "Annotate Animal Activity"),
        ("blank", "Annotate Blanks"),
    ]

    annotation_choices = forms.ChoiceField(
        choices=criteria, widget=forms.RadioSelect, label="Annotation Criteria", initial="blank"
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
                Column("annotation_choices", css_class="form-group col-12"),
            ),
            Row(
                Column(Submit("submit", "Annotate", css_class="form-group btn-primary")),
                css_class="text-center",
            ),
        )
        self.helper.form_show_errors = True


def get_daylight_savings_date(month, year):
    first_day_of_month = calendar.weekday(year=int(year), month=int(month), day=1)

    days_to_first_sunday = (6 - first_day_of_month + 1) % 7

    second_sunday_date = days_to_first_sunday + 7

    return datetime(year=int(year), month=int(month), day=second_sunday_date, hour=2)


class TimeCorrectionForm(forms.ModelForm):
    years = forms.IntegerField(required=False, initial=0)
    months = forms.IntegerField(required=False, initial=0)
    days = forms.IntegerField(required=False, initial=0)
    hours = forms.IntegerField(required=False, initial=0)
    minutes = forms.IntegerField(required=False, initial=0)

    daylight_savings = forms.CharField(
        widget=forms.TextInput(),
        required=False,
    )

    start_date = forms.DateTimeField(
        widget=forms.widgets.TextInput(attrs={"type": "datetime-local"}),
        required=False,
    )

    end_date = forms.DateTimeField(
        widget=forms.widgets.TextInput(attrs={"type": "datetime-local"}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                HTML("<h5>Incorrect Camera Date/Time</h5>"),
                HTML(
                    "<text class='small'>This is the offset that will be applied to the timestamps. Negative values will shift the times back.</text>"
                ),
                css_class="form-row mb-4 px-3",
            ),
            Row(
                Column("years", css_class="form-group"),
                Column("months", css_class="form-group"),
                Column("days", css_class="form-group"),
                Column("hours", css_class="form-group"),
                Column("minutes", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column("start_date", css_class="form-group"),
                Column("end_date", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                HTML("<h5>Daylight Savings Rollover</h5>"),
                HTML(
                    "<text class='small'>Timestamps will be shifted 1 hour forward/backward depending on the date.</text>"
                ),
                css_class="form-row mb-4 px-3",
            ),
            Row(
                Column("daylight_savings", css_class="form-group"),
                css_class="form-row mb-3 px-3",
            ),
            Row(
                Column(
                    Submit("submit", "Create Correction", css_class="btn-primary"),
                ),
                css_class="form-row text-center mb-3",
            ),
        )
        self.helper.form_show_errors = True

    class Meta:
        model = TimeCorrection

        fields = ["years", "months", "days", "hours", "minutes", "start_date", "end_date", "daylight_savings"]

    def clean_daylight_savings(self):
        date = self.cleaned_data.get("daylight_savings")

        if date and date != "":
            month, year = date.split("-")

            date_str = f"{year}-{month}-{get_daylight_savings_date(month, year).day:02d}"
        else:
            date_str = None

        return date_str
