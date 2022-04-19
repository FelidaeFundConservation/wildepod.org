from django.urls import path

from .views import ExploreDataView, ExploreHomeView, ExploreMapView, ExploreMegadetectorView, ExportDataView

urlpatterns = [
    path("", ExploreHomeView.as_view(), name="main"),
    path("data/", ExploreDataView.as_view(), name="data"),
    path("data/export/", ExportDataView.as_view(), name="data_export"),
    path("map/", ExploreMapView.as_view(), name="map"),
    path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
]
