"""
Django settings template for custom GCP App Engine deployments.

This is a TEMPLATE file. When using deploy_custom.sh, this structure will be
auto-generated with your custom environment name.

PLACEHOLDERS TO REPLACE:
- <ENV_NAME> → Your environment name in UPPERCASE_UNDERSCORE format (e.g., MY_DEV)
- <env-name> → Your environment name in lowercase-hyphen format (e.g., my-dev)
- <DATABASE_URL_VAR> → Database URL environment variable name (e.g., MY_DEV_DATABASE_URL)

DO NOT COMMIT: Custom environment files should be added to .gitignore
"""

import google.cloud.logging

from .base import *  # noqa

# HOSTS CONFIG
# ------------------------------------------------------------------------------
# NOTE: App Engine's security features ensure that it is safe to have
# ALLOWED_HOSTS = ['*'] when the app is deployed. If you deploy a Django
# app not on App Engine, make sure to set an appropriate host here.
ALLOWED_HOSTS = ["*"]

# DEBUG MODE
# ------------------------------------------------------------------------------
# Set to True for development, False for production
DEBUG = True


# WSGI APPLICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.<env-name>.application"

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
# Database URL should be set in Secret Manager as <DATABASE_URL_VAR>
# Format: postgres://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
DATABASES = {"default": env.db("<DATABASE_URL_VAR>")}

# If using Cloud SQL Auth Proxy for local development
if env.bool("USE_CLOUD_SQL_AUTH_PROXY", False):
    DATABASES["default"]["HOST"] = "127.0.0.1"
    DATABASES["default"]["PORT"] = 5440


# ADMIN
# ------------------------------------------------------------------------------
# Admin URL obfuscation - set ADMIN_URL_SUFFIX in Secret Manager
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
SECURE_HSTS_SECONDS = 60
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-include-subdomains
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-preload
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True)


# GCP SETTINGS
# ------------------------------------------------------------------------------
# Google Cloud Storage bucket for media files
GS_BUCKET_NAME = env("GS_BUCKET_NAME_PROD")
GS_DEFAULT_ACL = "publicRead"

# Media files configuration
DEFAULT_FILE_STORAGE = "siteapps.my_utils.storages.MediaRootGoogleCloudStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/media/"


# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="admin <noreply@wildepod.org>",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="[WildePod]",
)

# Mailgun email settings
# Set MAILGUN_SMTP_PASSWORD in Secret Manager
MAILGUN_SMTP_PASSWORD = env("MAILGUN_SMTP_PASSWORD")
EMAIL_HOST = "smtp.mailgun.org"
EMAIL_HOST_USER = "noreply@wildepod.org"
EMAIL_HOST_PASSWORD = MAILGUN_SMTP_PASSWORD
EMAIL_PORT = 587
EMAIL_USE_TLS = True


# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# https://googleapis.dev/python/logging/latest/std-lib-integration.html
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}


# EXTERNAL APPS CONFIG
# ------------------------------------------------------------------------------
# Dropbox configuration - environment-specific
# Set these in Secret Manager:
# - DROPBOX_APP_KEY_<ENV_NAME>
# - DROPBOX_APP_SECRET_<ENV_NAME>
# - DROPBOX_REFRESH_TOKEN_<ENV_NAME>
DROPBOX_APP_KEY = env("DROPBOX_APP_KEY_<ENV_NAME>")
DROPBOX_APP_SECRET = env("DROPBOX_APP_SECRET_<ENV_NAME>")
DROPBOX_REFRESH_TOKEN = env("DROPBOX_REFRESH_TOKEN_<ENV_NAME>")
DROPBOX_URL_PREFIX = "https://www.dropbox.com/work/WildePod%20Cloud%20DB/Apps/wildepod_<env-name>"


# CUSTOM VARIABLES
# ------------------------------------------------------------------------------
# Annotation configuration
NUM_ACCEPTS_OVER_REJECTS = 2

# Settings for Dropbox 2FA email retrieval
# Set these in Secret Manager
EMAIL_2FA_IMAP_URL = env("EMAIL_2FA_IMAP_URL_PROD")
EMAIL_2FA_USER = env("EMAIL_2FA_USER_PROD")
EMAIL_2FA_PASSWORD = env("EMAIL_2FA_PASSWORD_PROD")
