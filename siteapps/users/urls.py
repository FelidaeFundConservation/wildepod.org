# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.urls import path

from .views import (
    PrioritizeTaggingAnimalsView,
    UserUpdateView,
    VolunteerListView,
    VolunteerRegisterSuccessView,
    VolunteerRegisterView,
    VolunteerResendInviteView,
    VolunteerStatsView,
)

urlpatterns = [
    path("profile/", view=UserUpdateView.as_view(), name="profile"),
    path("volunteers/", view=VolunteerListView.as_view(), name="volunteers_list"),
    path("volunteers/stats/<uuid:pk>/", view=VolunteerStatsView.as_view(), name="volunteer_stats"),
    path("volunteers/add/", view=VolunteerRegisterView.as_view(), name="volunteer_add"),
    path("volunteers/add/success", view=VolunteerRegisterSuccessView.as_view(), name="volunteer_added"),
    path("prioritize_animals/", view=PrioritizeTaggingAnimalsView.as_view(), name="prioritize_animals"),
    path("volunteers/resend_invite/", view=VolunteerResendInviteView.as_view(), name="volunteer_resend_invite"),
]
