# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.conf import settings

# Auth pages whose URL carries a one-time key. Fundraise Up reads the page URL, so keep it off these.
FUNDRAISEUP_EXCLUDED_URL_NAMES = {
    "account_confirm_email",
    "account_reset_password_from_key",
}


def _fundraiseup_account_key(request):
    match = getattr(request, "resolver_match", None)
    if match and match.url_name in FUNDRAISEUP_EXCLUDED_URL_NAMES:
        return ""
    return settings.FUNDRAISEUP_ACCOUNT_KEY


def global_settings(request):
    return {
        # Add your context variables here
        "is_prod": "prod" in settings.WSGI_APPLICATION,
        "is_staging": "staging" in settings.WSGI_APPLICATION,
        "is_bhutan": "bhutan" in settings.WSGI_APPLICATION,
        "is_local": "local" in settings.WSGI_APPLICATION,
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        "fundraiseup_account_key": _fundraiseup_account_key(request),
        "fundraiseup_form": settings.FUNDRAISEUP_FORM,
        "fundraiseup_livemode": settings.FUNDRAISEUP_LIVEMODE,
    }
