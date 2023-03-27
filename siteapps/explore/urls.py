from django.urls import path, re_path

from .views import (
    ExploreIndexView,
    ExploreMapView,
    ExplorePopularImagesView,
    RemovePopularImageView,
    SearchDataView,
    SnapshotCreateView,
    SnapshotListView,
    SpeciesSightingTimeserieView,
    SpeciesSightingImagesView,
)

urlpatterns = [
    path("", ExploreMapView.as_view(), name="index"),
    path("data/snapshot/", SnapshotCreateView.as_view(), name="data_snapshot_create"),
    path("data/snapshots/", SnapshotListView.as_view(), name="data_snapshots"),
    path("map/", ExploreMapView.as_view(), name="map"),
    # path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
    path("popular-images/remove/<uuid:pk>/", RemovePopularImageView.as_view(), name="remove_popular_image"),
    path("popular-images/", ExplorePopularImagesView.as_view(), name="popular_images"),
    path("query_data/", SearchDataView.as_view(), name="query_data"),


    re_path("species/sighting/images/$", SpeciesSightingImagesView.as_view(), name="species_sighting_images"),
    re_path("species/(?P<species>.+)/$", SpeciesSightingTimeserieView.as_view(), name="species_sighting_timeserie_list"),
]
