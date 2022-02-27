from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class HelpView(LoginRequiredMixin, TemplateView):
    template_name = "help/help.html"
