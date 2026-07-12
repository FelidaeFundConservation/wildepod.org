# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.urls import path

from .views import HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="index"),
]
