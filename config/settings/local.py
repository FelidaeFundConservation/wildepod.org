"""Local env to do something quick, dirty and destructive. Uses a sqlite db to play around
"""
from .base import *

DEBUG = True

WSGI_APPLICATION = "config.wsgi.local.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

MEDIA_ROOT = Path.joinpath(BASE_DIR, "siteapps", "media")
STATIC_ROOT = Path.joinpath(BASE_DIR, "siteapps", "static_root")
STATICFILES_DIRS = [Path.joinpath(BASE_DIR, "siteapps", "static")]
