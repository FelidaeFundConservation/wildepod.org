from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views.generic import UpdateView

User = get_user_model()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    login_url = settings.LOGIN_URL
    template_name = "users/profile.html"
    fields = ["name", "phone_number"]
    success_message = "Information successfully updated"

    def get_success_url(self):
        return reverse("users:profile")

    def get_object(self):
        return self.request.user
