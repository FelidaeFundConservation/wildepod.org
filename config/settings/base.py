"""
Base settings to build other settings files upon.
"""
# This project follows the recommended structure from authors of two scoops of Django
# https://github.com/cookiecutter/cookiecutter-django
import io
import logging
import os
from pathlib import Path

import environ
from google.cloud import datastore, secretmanager

# Repo root
ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# siteapps/
APPS_DIR = ROOT_DIR / "siteapps"

# Create a django environ object with default getter as a bool
env = environ.Env(DEBUG=(bool, False))
# Local environment file path
env_file = ROOT_DIR / ".env"

# Local Development Environment related flags
# ------------------------------------------------------------------------------
# Detect if running in google cloud vs locally by checking for GCP environment variables
# K_SERVICE is set on Cloud Run, GAE_ENV is set on App Engine
RUNNING_ON_APP_ENGINE = os.environ.get("GAE_ENV")

# Check if running with local settings (no GCP dependencies)
USING_LOCAL_SETTINGS = os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".local")

# Note that you can run locally without local settings (eg:- debugging with staging/prod settings).
# However the reverse is not true, you cannot run in cloud with local settings.
if RUNNING_ON_APP_ENGINE and USING_LOCAL_SETTINGS:
    raise ValueError("Cannot run in cloud with local settings. Please use staging or prod settings.")

# Google Cloud Secret Manager
# ------------------------------------------------------------------------------
# Load environment variables from .env file or Google secret manager
# When running locally with local settings, we use the .env file and skip Secret Manager.
# In all other cases, (i.e. deployed to cloud, running locally with staging/prod settings) we use Secret Manager.
if USING_LOCAL_SETTINGS and not RUNNING_ON_APP_ENGINE:
    if env_file.is_file():
        env.read_env(env_file)
    else:
        raise ValueError("Local environment file not found. Please create a .env file in the root directory.")
else:
    if env("GOOGLE_CLOUD_PROJECT"):
        # Get project id & start a google secret manager client
        project_id = env("GOOGLE_CLOUD_PROJECT")
        client = secretmanager.SecretManagerServiceClient()
        # Secrets usually saved as "django_settings" in secret manager
        settings_name = env.str("SETTINGS_NAME", "django_settings")
        # Hardcoded path to get the latest secrets file
        name = f"projects/{project_id}/secrets/{settings_name}/versions/latest"
        payload = client.access_secret_version(name=name).payload.data.decode("UTF-8")
        # Read env variables from payload
        env.read_env(io.StringIO(payload))
    else:
        raise ValueError("Google Cloud project not found. Please set the GOOGLE_CLOUD_PROJECT environment variable.")


# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY")
# DEBUG MODE
DEBUG = False
# LOCAL ENVIRONMENT FLAG
# Detect if running locally vs in cloud by checking for GCP environment variables
# K_SERVICE is set on Cloud Run, GAE_ENV is set on App Engine
LOCAL = not os.environ.get("GAE_ENV")
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "America/Los_Angeles"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-l10n
USE_L10N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True


# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
# Databases are set for local, staging & prod separately
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"


# APPS
# ------------------------------------------------------------------------------
INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.humanize",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.forms",
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "siteapps.backyard",
    "siteapps.home",
    "siteapps.explore",
    "siteapps.users",
    "siteapps.inventory",
    "siteapps.locations",
    "siteapps.images",
    "simple_history",
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "/"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", False)
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_ADAPTER = "siteapps.users.adapters.AccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_MAX_EMAIL_ADDRESSES = 2
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_SESSION_REMEMBER = True
# https://django-allauth.readthedocs.io/en/latest/forms.html
ACCOUNT_FORMS = {"signup": "siteapps.users.forms.UserSignupForm"}


# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "siteapps.users.context_processors.allauth_settings",
                "siteapps.home.context_processors.global_settings",
            ],
        },
    }
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]
# WhiteNoise will handle all static files
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)


# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-browser-xss-filter
SECURE_BROWSER_XSS_FILTER = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

DATA_UPLOAD_MAX_NUMBER_FIELDS = 1350

# JAZZMIN
# ------------------------------------------------------------------------------
# Jazzmin admin site customization
# https://django-jazzmin.readthedocs.io/configuration/
JAZZMIN_SETTINGS = {
    "site_title": "WildePod Admin",
    "site_header": "WildePod Admin",
    # Logo to use for your site, must be present in static files, used for brand on top left
    # "site_logo": "books/img/logo.png",
    # CSS classes that are applied to the logo above
    "site_logo_classes": "img-circle",
    # Relative path to a favicon for your site, will default to site_logo if absent (ideally 32x32 px)
    "site_icon": None,
    "welcome_sign": "Welcome to WildePod Admin",
    "copyright": "Felidae Conservation Fund",
    # Links to put along the top menu
    "topmenu_links": [
        {"name": "Admin", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Back to Site", "url": "/"},
    ],
    # List of apps (and/or models) to base side menu ordering off of (does not need to contain all apps/models)
    "order_with_respect_to": [
        "auth",
        "users",
        "account",
        "inventory",
        "inventory.Camera",
        "inventory.CameraModel",
        "inventory.CameraBrand",
        "locations",
        "locations.CameraTrap",
        "locations.MicroSite",
        "locations.Grid",
        "locations.MacroSite",
        "locations.County",
        "locations.Area",
        "images",
        "images.Upload",
        "images.Image",
        "images.Annotation",
    ],
}

# CUSTOM VARIABLES
# ------------------------------------------------------------------------------
# GCF cloud url where MegaDetector currently serves requests
# Optional for local development (will error if ML inference is attempted without these)
MEGADETECTOR_URL = env("MEGADETECTOR_URL", default=None)
SPECIES_DETECTOR_URL = env("SPECIES_DETECTOR_URL", default=None)
# Model storage bucket name & relevant model URLs
MODEL_STORAGE_BUCKET = env("GS_MODELS_BUCKET_NAME", default=None)
MIN_MEGADETECTOR_CONFIDENCE = 0.25

# Initialize a Datastore client (only for non-local environments)
if not USING_LOCAL_SETTINGS:
    DATASTORE_CLIENT = datastore.Client(env("GOOGLE_CLOUD_PROJECT"))
else:
    DATASTORE_CLIENT = None  # Local development doesn't use Datastore

ANNOTATION_QUEUE_SIZE = 100
ANNOTATION_EXPIRATION_MINS = 60  # minutes

# EXPORT SERVICE AND TASK QUEUE DETAILS
# ------------------------------------------------------------------------------
GCP_PROJECT_ID = env("GOOGLE_CLOUD_PROJECT", default=None)
GCP_REGION = "us-west2"  # TODO: This can be fetched via the cloud tasks API
EXPORT_SERVICE_NAME = "jobs"
EXPORT_QUEUE_NAME = "wildepod-jobs-queue"
EXPORT_DATE_FORMAT = "%Y-%m-%d"
EXPORT_URL_SUFFIX = "8jk6fh9m7w2xz5r3t1n0b8v6c"  # TODO: Move this to secret manager

# Google Maps API (optional for local development)
GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', default=None)