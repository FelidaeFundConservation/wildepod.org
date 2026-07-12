# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings
from django.shortcuts import render
from django.views.generic.base import TemplateView

# Create your views here.


class HomeView(TemplateView):
    template_name = "backyard/home.html"


class TermsOfServiceView(TemplateView):
    template_name = "backyard/terms.html"


class PrivacyPolicyView(TemplateView):
    template_name = "backyard/privacy.html"


class DeleteAccountInfoView(TemplateView):
    template_name = "backyard/delete_account.html"
