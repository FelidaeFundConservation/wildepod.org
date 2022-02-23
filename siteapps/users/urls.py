from django.urls import path

from .views import UserUpdateView

urlpatterns = [
    path("", view=UserUpdateView.as_view(), name="profile"),
]
