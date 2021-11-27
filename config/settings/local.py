"""Local env to do something quick, dirty and destructive. Uses a sqlite db to play around
"""
from .base import *

DEBUG = True

WSGI_APPLICATION = "config.wsgi.local.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

STATIC_URL = "/static/"
MEDIA_ROOT = os.path.join(BASE_DIR, "siteapps", "media")
STATICFILES_DIRS = [os.path.join(BASE_DIR, "siteapps", "static")]
