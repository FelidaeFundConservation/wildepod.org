from django.urls import path

from .views import InstructionsView

urlpatterns = [
    path("", InstructionsView.as_view(), name="index"),
]
