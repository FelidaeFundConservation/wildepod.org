import io
import os
import sys

import environ
from google.cloud import secretmanager

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(os.path.join(BASE_DIR, "siteapps"))

# Read env variables
env = environ.Env(DEBUG=(bool, False))
env_file = os.path.join(BASE_DIR, ".env")


# If there is a local secret file, load. Otherwise, pull it from gcloud
if os.path.isfile(env_file):
    env.read_env(env_file)
elif os.environ.get("GOOGLE_CLOUD_PROJECT", None):
    # Pull secrets from Secret Manager
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    client = secretmanager.SecretManagerServiceClient()
    settings_name = os.environ.get("SETTINGS_NAME", "django_settings")
    name = f"projects/{project_id}/secrets/{settings_name}/versions/latest"
    payload = client.access_secret_version(name=name).payload.data.decode("UTF-8")

    env.read_env(io.StringIO(payload))

SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: App Engine's security features ensure that it is safe to
# have ALLOWED_HOSTS = ['*'] when the app is deployed. If you deploy a Django
# app not on App Engine, make sure to set an appropriate host here.
ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "siteapps.home",
    "siteapps.explore",
    "siteapps.profiles",
    "siteapps.inventory",
    "siteapps.locations",
    "siteapps.images",
    "siteapps.help",
    "crispy_forms",
    "crispy_bootstrap5",
    "simple_history",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "siteapps", "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Admin url obfuscation
ADMIN_SECRET_SUFFIX = env("ADMIN_SECRET_SUFFIX")

# Model storage bucket name & relevant model URLs
MODEL_STORAGE_BUCKET = env("GS_MODELS_STORAGE_BUCKET_NAME")
MEGADETECTOR_URL = env("MEGADETECTOR_URL")

# Account settings
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Override default user model
AUTH_USER_MODEL = "profiles.Profile"

# Jazzmin admin site customization
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
        "profiles",
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

# Crispy form settings
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
