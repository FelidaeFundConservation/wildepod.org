from .base import *

DEBUG = True

WSGI_APPLICATION = "config.wsgi.staging.application"

DATABASES = {"default": env.db("STAGING_DATABASE_URL")}

# If the flag as been set, configure to use proxy
if os.getenv("USE_CLOUD_SQL_AUTH_PROXY", None):
    DATABASES["default"]["HOST"] = "127.0.0.1"
    DATABASES["default"]["PORT"] = 5434

# Google cloud dev setting
GS_BUCKET_NAME = env("GS_BUCKET_NAME")
DEFAULT_FILE_STORAGE = "storages.backends.gcloud.GoogleCloudStorage"
STATICFILES_STORAGE = "storages.backends.gcloud.GoogleCloudStorage"

MEDIA_ROOT = Path.joinpath(BASE_DIR, "siteapps", "media")
STATIC_ROOT = Path.joinpath(BASE_DIR, "siteapps", "static_root")
STATICFILES_DIRS = [Path.joinpath(BASE_DIR, "siteapps", "static")]
