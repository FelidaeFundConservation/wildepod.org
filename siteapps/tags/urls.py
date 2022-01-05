from django.urls import path

from .views import MegaDetectorDemoView, TagBlankView, TagSpeciesView

urlpatterns = [
    path("blank/", TagBlankView.as_view(), name="blank"),
    path("species/", TagSpeciesView.as_view(), name="species"),
    path("md-demo/", MegaDetectorDemoView.as_view(), name="md-demo"),
]
