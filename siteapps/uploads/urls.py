from django.urls import path

from .views import UploadCreateView, UploadDetailView, UploadFinalizeView, UploadListView

urlpatterns = [
    path("", UploadListView.as_view(), name="list"),
    path("<int:pk>/", UploadDetailView.as_view(), name="detail"),
    path("create/", UploadCreateView.as_view(), name="create"),
    path("finalize/<int:pk>/", UploadFinalizeView.as_view(), name="finalize"),
]
