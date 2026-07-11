# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings


def global_settings(request):
    return {
        # Add your context variables here
        "is_prod": "prod" in settings.WSGI_APPLICATION,
        "is_staging": "staging" in settings.WSGI_APPLICATION,
        "is_bhutan": "bhutan" in settings.WSGI_APPLICATION,
        "is_local": "local" in settings.WSGI_APPLICATION,
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
    }
