# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Dropbox client factory for creating Dropbox instances."""

import dropbox
from django.conf import settings


def create_dropbox_client():
    """Create and return a Dropbox client, or None if credentials not configured."""
    if settings.DROPBOX_APP_KEY and settings.DROPBOX_APP_SECRET and settings.DROPBOX_REFRESH_TOKEN:
        return dropbox.Dropbox(
            app_key=settings.DROPBOX_APP_KEY,
            app_secret=settings.DROPBOX_APP_SECRET,
            oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
        )
    return None
