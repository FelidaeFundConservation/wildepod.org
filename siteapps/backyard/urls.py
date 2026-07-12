# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.urls import path

from .views import DeleteAccountInfoView, HomeView, PrivacyPolicyView, TermsOfServiceView

urlpatterns = [
    path("", HomeView.as_view(), name="backyard_home"),
    path("terms", TermsOfServiceView.as_view(), name="backyard_terms"),
    path("privacy", PrivacyPolicyView.as_view(), name="backyard_privacy"),
    path("delete_account", DeleteAccountInfoView.as_view(), name="backyard_delete_account"),
]
