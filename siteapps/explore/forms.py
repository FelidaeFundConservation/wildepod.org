from django import forms


class ExploreMegadetectorForm(forms.Form):
    url = forms.URLField(label="Image Url", max_length=1000, required=False)
    image = forms.ImageField(required=False)
