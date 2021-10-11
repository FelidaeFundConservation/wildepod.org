from django.urls import path

from .views import TagView

urlpatterns = [
    path("", TagView.as_view(), name="tag"),
]
