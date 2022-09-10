from django.urls import path

from .views import (  # ExploreMegadetectorView,
    ExploreIndexView,
    ExploreMapView,
    ExplorePopularImagesView,
    SnapshotCreateView,
    SnapshotListView,
)

urlpatterns = [
    path("", ExploreMapView.as_view(), name="index"),
    path("data/snapshot/", SnapshotCreateView.as_view(), name="data_snapshot_create"),
    path("data/snapshots/", SnapshotListView.as_view(), name="data_snapshots"),
    path("map/", ExploreMapView.as_view(), name="map"),
    # path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
    path("popular-images/", ExplorePopularImagesView.as_view(), name="popular_images"),
]
