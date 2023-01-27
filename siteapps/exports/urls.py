from django.conf import settings
from django.urls import path

from .views import ExportStartView, HelloWorldView

urlpatterns = [
    path(f"start/{settings.EXPORT_URL_SUFFIX}/", ExportStartView.as_view(), name="start"),
]
