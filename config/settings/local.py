# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Local env to do something quick, dirty and destructive. Uses a sqlite db to play around
"""

from .base import *  # noqa

# HOSTS CONFIG
# ------------------------------------------------------------------------------
# NOTE: SECURITY WARNING: App Engine's security features ensure that it is safe to
# have ALLOWED_HOSTS = ['*'] when the app is deployed. If you deploy a Django
# app not on App Engine, make sure to set an appropriate host here.
ALLOWED_HOSTS = ["*"]

# DEBUG MODE
# ------------------------------------------------------------------------------
DEBUG = True

# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.local.application"

# django-debug-toolbar
# ------------------------------------------------------------------------------
# Makes page loads extremely slow so use sparingly
# # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
# INSTALLED_APPS += ["debug_toolbar"]  # noqa F405
# # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
# MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa F405
# # https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
# DEBUG_TOOLBAR_CONFIG = {
#     "DISABLE_PANELS": ["debug_toolbar.panels.redirects.RedirectsPanel"],
#     "SHOW_TEMPLATE_CONTEXT": True,
# }
# # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
# INTERNAL_IPS = ["127.0.0.1", "10.0.2.2", "localhost"]


# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
# Using SQLite for local development (no PostgreSQL setup needed)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(ROOT_DIR / "db.sqlite3"),  # noqa F405
    }
}


# TODO: Check if this needs to be done
# DATABASES["default"]["ATOMIC_REQUESTS"] = True


# ADMIN
# ------------------------------------------------------------------------------
# Admin url obfuscation
ADMIN_URL_SUFFIX = ""


# MEDIA
# ------------------------------------------------------------------------------
# Use local file storage instead of Google Cloud Storage for local development
MEDIA_ROOT = str(ROOT_DIR / "media")  # noqa F405
MEDIA_URL = "/media/"
# NOTE: MEDIA_URL must stay relative here -- config/urls.py serves media via
# django.conf.urls.static.static(), which returns no routes at all if MEDIA_URL has a
# netloc. views.annotation.get_pil_image() reads thumbnails straight off MEDIA_ROOT when
# MEDIA_URL is relative, so local thumbnails work without an absolute URL.
# Note: For local development, you'll need to serve media files with:
# python manage.py runserver --insecure (or configure your local server to serve media)


# DATASTORE
# ------------------------------------------------------------------------------
# base.py sets DATASTORE_CLIENT = None for local settings, which makes every annotation
# view raise AttributeError on settings.DATASTORE_CLIENT.key(...). Swap in an in-memory
# stand-in so the annotation queues (including the staff review queue) work locally.
# State is per-process and resets on autoreload.
from ._local_datastore import LocalDatastoreClient  # noqa: E402

DATASTORE_CLIENT = LocalDatastoreClient()

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5


# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]  # noqa F405

# EXTERNAL APPS CONFIG
# ------------------------------------------------------------------------------
# Dropbox credentials are optional for local development
DROPBOX_APP_KEY = env("DROPBOX_APP_KEY_STAGING", default=None)
DROPBOX_APP_SECRET = env("DROPBOX_APP_SECRET_STAGING", default=None)
DROPBOX_REFRESH_TOKEN = env("DROPBOX_REFRESH_TOKEN_STAGING", default=None)
DROPBOX_URL_PREFIX = "https://www.dropbox.com/work/WildePod%20Cloud%20DB/Apps/wildepod_staging"


# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"}},
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}


# CUSTOM VARIABLES
# ------------------------------------------------------------------------------
# Annotation configuration
NUM_ACCEPTS_OVER_REJECTS = 2

# Export URL suffix is not needed locally; override base with an empty default
EXPORT_URL_SUFFIX = env("EXPORT_URL_SUFFIX", default="")
