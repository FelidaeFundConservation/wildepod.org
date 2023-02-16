from django.urls import path

from .views import (
    ActivityAnnotationProcessorView,  # UploadExportView,
    AnnotateActivityView,
    AnnotateObjectsView,
    AnnotateSpeciesView,
    ImageDetailView,
    MDAnnotationProcessorView,
    SpeciesAnnotationProcessorView,
    UploadCompleteView,
    UploadCreateView,
    UploadDetailView,
    UploadListView,
    UploadResumeProcessingView,
    UploadStatusView,
)

urlpatterns = [
    path("uploads/", UploadListView.as_view(), name="list_uploads"),
    path(
        "uploads/status/",
        UploadStatusView.as_view(),
        name="upload_status",
    ),
    path(
        "uploads/resume-processing/",
        UploadResumeProcessingView.as_view(),
        name="upload_resume_processing",
    ),
    path("upload/", UploadCreateView.as_view(), name="create_upload"),
    path("upload/<uuid:pk>/", UploadDetailView.as_view(), name="view_upload"),
    path(
        "upload/<uuid:pk>/complete",
        UploadCompleteView.as_view(),
        name="complete_upload",
    ),
    # path("upload/<uuid:pk>/export/", UploadExportView.as_view(), name="export_upload"),
    path("image/<uuid:pk>", ImageDetailView.as_view(), name="image"),
    path("annotate/objects", AnnotateObjectsView.as_view(), name="annotate_objects"),
    path("annotate/species", AnnotateSpeciesView.as_view(), name="annotate_species"),
    path("annotate/activity/<str:category>", AnnotateActivityView.as_view(), name="annotate_activity"),
    path(
        "md-annotation-processor/",
        MDAnnotationProcessorView.as_view(),
        name="md_annotation_processor",
    ),
    path(
        "species-annotation-processor/",
        SpeciesAnnotationProcessorView.as_view(),
        name="species_annotation_processor",
    ),
    path(
        "activity-annotation-processor/",
        ActivityAnnotationProcessorView.as_view(),
        name="activity_annotation_processor",
    ),
]
