from django.urls import path

from .views import HomeView, PrivacyPolicyView, TermsOfServiceView

urlpatterns = [
    path("", HomeView.as_view(), name="backyard_home"),
    path("terms", TermsOfServiceView.as_view(), name="backyard_terms"),
    path("privacy", PrivacyPolicyView.as_view(), name="backyard_privacy"),
]
