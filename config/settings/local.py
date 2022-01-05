"""Local env to do something quick, dirty and destructive. Uses a sqlite db to play around
"""
from .base import *

DEBUG = True

IS_GCP = False

WSGI_APPLICATION = "config.wsgi.local.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

# Dropbox auth token for local mode
DROPBOX_AUTH_TOKEN = env("DROPBOX_AUTH_TOKEN_LOCAL")

# Static file config. For local mode, this will be served by django
STATIC_URL = "/static/"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "siteapps", "static")]
# This is a hacky value setting for local mode since the config value is expected in custom_storages.py
GS_STATIC_STORAGE_BUCKET_NAME = None

# Django media setting for local mode that uses dev buckets
GS_MEDIA_STORAGE_BUCKET_NAME = env("GS_MEDIA_STORAGE_BUCKET_NAME_DEV")
GS_DEFAULT_ACL = "publicRead"
DEFAULT_FILE_STORAGE = "config.settings.custom_storages.MediaStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_MEDIA_STORAGE_BUCKET_NAME}/"

MEGADETECTOR_URL = f"http://localhost:8080"
