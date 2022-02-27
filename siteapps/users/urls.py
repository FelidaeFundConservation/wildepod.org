from django.urls import path

from .views import UserUpdateView, VolunteerListView, VolunteerRegisterSuccessView, VolunteerRegisterView

urlpatterns = [
    path("profile/", view=UserUpdateView.as_view(), name="profile"),
    path("volunteers/", view=VolunteerListView.as_view(), name="volunteers_list"),
    path("volunteers/add/", view=VolunteerRegisterView.as_view(), name="volunteer_add"),
    path("volunteers/add/success", view=VolunteerRegisterSuccessView.as_view(), name="volunteer_added"),
]
