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
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(ROOT_DIR / "db.sqlite3"),
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
GS_BUCKET_NAME = env("GS_BUCKET_NAME_DEV")
GS_DEFAULT_ACL = "publicRead"
DEFAULT_FILE_STORAGE = "siteapps.utils.storages.MediaRootGoogleCloudStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/media/"

CKEDITOR_UPLOAD_PATH = "ckeditor_uploads/"

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
DROPBOX_APP_KEY = env("DROPBOX_APP_KEY_STAGING")
DROPBOX_APP_SECRET = env("DROPBOX_APP_SECRET_STAGING")
DROPBOX_REFRESH_TOKEN = env("DROPBOX_REFRESH_TOKEN_STAGING")
DROPBOX_URL_PREFIX = "https://www.dropbox.com/personal/Apps/WildePod_staging/"


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


# COMPRESSOR
# ------------------------------------------------------------------------------
COMPRESS_ENABLED = False

COMPRESS_PRECOMPILERS = (
    ("text/x-sass", "sass --style compressed {infile} {outfile}"),
    ("text/x-scss", "sass --style compressed {infile} {outfile}"),
)


# CUSTOM VARIABLES
# ------------------------------------------------------------------------------
# GCF cloud url where MegaDetector currently serves requests
MEGADETECTOR_URL = env("MEGADETECTOR_URL_LOCAL")

# Annotation configuration
NUM_ACCEPTS_OVER_REJECTS = 0
MIN_MEGADETECTOR_CONFIDENCE = 0.25
