from django.views.generic import TemplateView
from typing import Any, Dict

class HomeView(TemplateView):
    template_name = "home/home.html"