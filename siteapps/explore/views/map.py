# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from locations.models import CameraStation


class ExploreMapView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = CameraStation
    template_name = "explore/map.html"
