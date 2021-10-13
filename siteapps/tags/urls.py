from django.urls import path

from .views import TagBlankView, TagSpeciesView

urlpatterns = [
    path("blank", TagBlankView.as_view(), name="blank"),
    path("species", TagSpeciesView.as_view(), name="species"),
]
