"""This is the final production setting
"""
import google.cloud.logging

from .base import *  # noqa

# HOSTS CONFIG
# ------------------------------------------------------------------------------
# NOTE: SECURITY WARNING: App Engine's security features ensure that it is safe to
# have ALLOWED_HOSTS = ['*'] when the app is deployed. If you deploy a Django
# app not on App Engine, make sure to set an appropriate host here.
ALLOWED_HOSTS = ["*"]

# DEBUG MODE
# ------------------------------------------------------------------------------
DEBUG = False

# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.prod.application"

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {"default": env.db("PROD_DATABASE_URL")}
# TODO: Check if this needs to be done

# If the flag has been set, configure to use proxy
if env.bool("USE_CLOUD_SQL_AUTH_PROXY", False):
    DATABASES["default"]["HOST"] = "127.0.0.1"
    DATABASES["default"]["PORT"] = 5434
# TODO: Check if this needs to be done
# DATABASES["default"]["ATOMIC_REQUESTS"] = True


# ADMIN
# ------------------------------------------------------------------------------
# Admin url obfuscation
ADMIN_URL_SUFFIX = env.str("ADMIN_URL_SUFFIX", default="")


# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-secure
SESSION_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-secure
CSRF_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/topics/security/#ssl-https
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-seconds
# TODO: set this to 60 seconds first and then to 518400 once you prove the former works
SECURE_HSTS_SECONDS = 60
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-include-subdomains
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-preload
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True)


# GCP settings
# ------------------------------------------------------------------------------
GS_BUCKET_NAME = env("GS_BUCKET_NAME_PROD")
GS_DEFAULT_ACL = "publicRead"
# Static files
STATICFILES_STORAGE = "siteapps.utils.storages.StaticRootGoogleCloudStorage"
COLLECTFAST_STRATEGY = "collectfast.strategies.gcloud.GoogleCloudStrategy"
STATIC_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/static/"
# Media files
DEFAULT_FILE_STORAGE = "siteapps.utils.storages.MediaRootGoogleCloudStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/media/"

CKEDITOR_UPLOAD_PATH = "ckeditor_uploads/"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="Admin <noreply@wildepod.org>",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="[WildePod]",
)
# Sendgrid email settings
SENDGRID_API_KEY = env("SENDGRID_API_KEY")
EMAIL_HOST = "smtp.sendgrid.net"
EMAIL_HOST_USER = "apikey"
EMAIL_HOST_PASSWORD = SENDGRID_API_KEY
EMAIL_PORT = 587
EMAIL_USE_TLS = True


# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# https://googleapis.dev/python/logging/latest/std-lib-integration.html
# Logging into Google Cloud

# Instantiates a client
google_logging_client = google.cloud.logging.Client()

# Retrieves a Cloud Logging handler based on the environment
# you're running in and integrates the handler with the
# Python logging module. By default this captures all logs
# at INFO level and higher
google_logging_client.setup_logging()


# EXTERNAL APPS CONFIG
# ------------------------------------------------------------------------------
DROPBOX_APP_KEY = env("DROPBOX_APP_KEY_PROD")
DROPBOX_APP_SECRET = env("DROPBOX_APP_SECRET_PROD")
DROPBOX_REFRESH_TOKEN = env("DROPBOX_REFRESH_TOKEN_PROD")
DROPBOX_URL_PREFIX = "https://www.dropbox.com/home/Felidae%20Fund/Apps/WildePod_prod"

# CUSTOM VARIABLES
# ------------------------------------------------------------------------------
# Annotation configuration
NUM_ACCEPTS_OVER_REJECTS = 2
MIN_MEGADETECTOR_CONFIDENCE = 0.25
