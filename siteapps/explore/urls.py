from django.urls import path

from .views import (
    ExploreDataView,
    ExploreIndexView,
    ExploreMapView,
    ExploreMegadetectorView,
    ExplorePopularImagesView,
    ExportDataView,
)

urlpatterns = [
    path("", ExploreMapView.as_view(), name="index"),
    # TODO: Enable/modify these urls when the corresponding views are ready
    # path("data/", ExploreDataView.as_view(), name="data"),
    # path("data/export/", ExportDataView.as_view(), name="data_export"),
    path("map/", ExploreMapView.as_view(), name="map"),
    path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
    path("popular-images/", ExplorePopularImagesView.as_view(), name="popular_images"),
]
