from .base import *

DEBUG = False

IS_GCP = True

WSGI_APPLICATION = "config.wsgi.prod.application"

DATABASES = {"default": env.db("PROD_DATABASE_URL")}

# Custom django env settings
DROPBOX_AUTH_TOKEN = env("DROPBOX_AUTH_TOKEN_PROD")

# If the flag has been set, configure to use proxy
if os.getenv("USE_CLOUD_SQL_AUTH_PROXY", None):
    DATABASES["default"]["HOST"] = "127.0.0.1"
    DATABASES["default"]["PORT"] = 5434

# Static & media storage config for prod
GS_STATIC_STORAGE_BUCKET_NAME = env("GS_STATIC_STORAGE_BUCKET_NAME_PROD")
GS_MEDIA_STORAGE_BUCKET_NAME = env("GS_MEDIA_STORAGE_BUCKET_NAME_PROD")
GS_DEFAULT_ACL = "publicRead"

STATICFILES_DIRS = [os.path.join(BASE_DIR, "siteapps", "static")]
STATICFILES_STORAGE = "config.settings.custom_storages.StaticStorage"
STATIC_URL = f"https://storage.googleapis.com/{GS_STATIC_STORAGE_BUCKET_NAME}/"

DEFAULT_FILE_STORAGE = "config.settings.custom_storages.MediaStorage"
MEDIA_URL = f"https://storage.googleapis.com/{GS_MEDIA_STORAGE_BUCKET_NAME}/"
