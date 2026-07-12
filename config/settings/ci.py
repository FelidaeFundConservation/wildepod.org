"""CI settings for GitHub Actions. Extends base only — no cloud credentials required."""

from .base import *  # noqa

DEBUG = True

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
GS_BUCKET_NAME = "ci-placeholder"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
MAILGUN_SMTP_PASSWORD = "ci-placeholder"

DROPBOX_APP_KEY = ""
DROPBOX_APP_SECRET = ""
DROPBOX_REFRESH_TOKEN = ""
DROPBOX_URL_PREFIX = ""

EMAIL_2FA_IMAP_URL = ""
EMAIL_2FA_USER = ""
EMAIL_2FA_PASSWORD = ""

SECURE_SSL_REDIRECT = False
ADMIN_URL_SUFFIX = ""

WSGI_APPLICATION = "config.wsgi.staging.application"

NUM_ACCEPTS_OVER_REJECTS = 2

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
