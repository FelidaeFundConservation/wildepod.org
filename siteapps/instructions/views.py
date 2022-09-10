from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .models import Instructions


class InstructionsView(LoginRequiredMixin, TemplateView):
    template_name = "instructions/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["instructions"] = Instructions.objects.filter(active=True)[0]
        return context
