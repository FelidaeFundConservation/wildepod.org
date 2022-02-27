from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import forms as admin_forms
from django.contrib.auth import get_user_model

User = get_user_model()


class UserAdminCreationForm(admin_forms.UserCreationForm):
    class Meta(admin_forms.UserCreationForm.Meta):
        model = User
        fields = (
            "email",
            "name",
        )

        error_messages = {"email": {"unique": "This email has already been registered."}}


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):
        model = User
        fields = (
            "email",
            "name",
        )


class UserSignupForm(SignupForm):
    """
    Form that will be rendered on a user sign up section/screen.
    Default fields will be added automatically.
    Check UserSocialSignupForm for accounts created from social.
    """

    pass


class RegisterVolunteerForm(forms.Form):
    email = forms.EmailField(required=True)
    name = forms.CharField(max_length=100, required=False)
    phone_number = forms.CharField(max_length=25, required=False)
