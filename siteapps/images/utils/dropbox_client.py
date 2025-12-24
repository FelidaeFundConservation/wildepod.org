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
