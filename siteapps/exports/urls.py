# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings
from django.urls import path

from .views import ExportStartView

urlpatterns = [
    path(f"start/{settings.EXPORT_URL_SUFFIX}/", ExportStartView.as_view(), name="start"),
]
