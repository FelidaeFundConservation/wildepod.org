from django.urls import path

from .views import UploadCreateView, UploadFinalizeView, UploadListView

urlpatterns = [
    path("", UploadListView.as_view(), name="list"),
    path("upload/", UploadCreateView.as_view(), name="upload"),
    path("finalize/<int:pk>/", UploadFinalizeView.as_view(), name="finalize"),
]
