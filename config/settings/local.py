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

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
GS_BUCKET_NAME = env("GS_BUCKET_NAME_DEV")
GS_DEFAULT_ACL = "publicRead"
DEFAULT_FILE_STORAGE = "siteapps.utils.storages.MediaRootGoogleCloudStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_BUCKET_NAME}/media/"


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
# Dropbox token for local mode
DROPBOX_AUTH_TOKEN = env("DROPBOX_AUTH_TOKEN_LOCAL")
DROPBOX_URL_PREFIX = "https://www.dropbox.com/home/Apps/abhay_test/"
