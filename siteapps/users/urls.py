from django.urls import path

from .views import UserUpdateView

urlpatterns = [
    path("profile", view=UserUpdateView.as_view(), name="profile"),
]
