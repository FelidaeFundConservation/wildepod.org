from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class ExploreIndexView(LoginRequiredMixin, TemplateView):
    template_name = "explore/index.html"
