from django import forms


class MLDemoForm(forms.Form):
    url = forms.URLField(label="Image Url", max_length=1000, required=False)
    image = forms.ImageField(required=False)
