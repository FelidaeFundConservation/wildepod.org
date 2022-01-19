from django.urls import path

from .views import (
    ImageDetailView,
    MDAnnotationProcessorView,
    UploadCompleteView,
    UploadCreateView,
    UploadDetailView,
    UploadListView,
)

urlpatterns = [
    path("uploads/", UploadListView.as_view(), name="list_uploads"),
    path("upload/", UploadCreateView.as_view(), name="create_upload"),
    path("upload/<uuid:pk>/", UploadDetailView.as_view(), name="view_upload"),
    path("upload/<uuid:pk>/complete", UploadCompleteView.as_view(), name="complete_upload"),
    path("image/<uuid:pk>", ImageDetailView.as_view(), name="image"),
    path("md-annotation-processor/", MDAnnotationProcessorView.as_view(), name="md_annotation_processor"),
]
