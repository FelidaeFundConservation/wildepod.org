from django.urls import path

from .views import (
    ExploreIndexView,
    ExploreMapView,
    ExplorePopularImagesView,
    SearchDataView,
    SnapshotCreateView,
    SnapshotListView,
    RemovePopularImage,
)

urlpatterns = [
    path("", ExploreMapView.as_view(), name="index"),
    path("data/snapshot/", SnapshotCreateView.as_view(), name="data_snapshot_create"),
    path("data/snapshots/", SnapshotListView.as_view(), name="data_snapshots"),
    path("map/", ExploreMapView.as_view(), name="map"),
    # path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
    path("popular-images/remove/<uuid:pk>/", RemovePopularImage.as_view(), name="remove_popular_image"),
    path("popular-images/", ExplorePopularImagesView.as_view(), name="popular_images"),
    path("query_data/", SearchDataView.as_view(), name="query_data"),





]
