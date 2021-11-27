from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView, UpdateView

# from .models import HelpPage


class HelpView(TemplateView):
    template_name = "help/help.html"


# class HelpUpdateView(LoginRequiredMixin, UpdateView):
#     model = HelpPage
#     login_url = settings.LOGIN_URL
#     template_name = "help/edit.html"

#     def get_success_url(self):
#         return reverse("help:index")
