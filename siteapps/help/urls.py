from django.urls import path

from .views import HelpView  # , HelpUpdateView

urlpatterns = [
    path("", HelpView.as_view(), name="index"),
    # path("<int:pk>/update/", HelpUpdateView.as_view(), name="update"),
]
