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
WSGI_APPLICATION = "config.wsgi.dev.application"

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DATABASES = {"default": env.db("DEV_DATABASE_URL")}

# ADMIN
# ------------------------------------------------------------------------------
# Admin url obfuscation
ADMIN_URL_SUFFIX = ""


# MEDIA
# ------------------------------------------------------------------------------
# GS_BUCKET_NAME = env("GS_BUCKET_NAME_DEV")
GS_BUCKET_NAME = env("GS_BUCKET_NAME_DEV")
GS_DEFAULT_ACL = "publicRead"
DEFAULT_FILE_STORAGE = "siteapps.my_utils.storages.MediaRootGoogleCloudStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/media/"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5


# EXTERNAL APPS CONFIG
# ------------------------------------------------------------------------------
DROPBOX_APP_KEY = env("DROPBOX_APP_KEY_DEV")
DROPBOX_APP_SECRET = env("DROPBOX_APP_SECRET_DEV")
DROPBOX_REFRESH_TOKEN = env("DROPBOX_REFRESH_TOKEN_DEV")
DROPBOX_URL_PREFIX = "https://www.dropbox.com/work/WildePod%20Cloud%20DB/Apps/wildepod_prod"


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
