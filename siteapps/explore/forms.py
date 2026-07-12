# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from crispy_forms.bootstrap import StrictButton
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Column, Layout, Row, Submit
from django import forms
from explore.models import Snapshot


# NOTE: THIS IS DEPRECATED
class ExploreMegadetectorForm(forms.Form):
    url = forms.URLField(label="Image Url", max_length=1000, required=False)
    image = forms.ImageField(required=False)


class CreateSnapshotForm(forms.ModelForm):

    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={"type": "date"}), required=False)

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
            # Row(
            #     Column("annotated_only", css_class="form-group col-12"),
            #     css_class="text-center",
            # ),
            Row(
                Column(Submit("submit", "Create Snapshot", css_class="form-group btn-primary w-50")),
                css_class="text-center py-2",
            ),
        )
        self.helper.form_show_errors = True

    class Meta:
        model = Snapshot
        start_date = forms.DateField()
        end_date = forms.DateField()
        fields = [
            "start_date",
            "end_date",
            "macrosites",
            # "annotated_only"
        ]

        labels = {
            "macrosites": "Filter by Macrosite",
            # "annotated_only": "Only include images with annotations",
        }
