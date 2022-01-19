from django.urls import path

from .views import ExploreHomeView, ExploreMapView, ExploreMegadetectorView

urlpatterns = [
    path("", ExploreHomeView.as_view(), name="main"),
    path("map/", ExploreMapView.as_view(), name="map"),
    path("megadetector/", ExploreMegadetectorView.as_view(), name="megadetector"),
]
