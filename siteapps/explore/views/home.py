from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class ExploreHomeView(LoginRequiredMixin, TemplateView):
    template_name = "explore/main.html"
