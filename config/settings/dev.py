"""Dev environment is set to build directly off Google cloud backend. This is to ensure smoother transition into
staging/prod systems
"""
from .base import *

DEBUG = True

WSGI_APPLICATION = "config.wsgi.dev.application"

DATABASES = {"default": env.db("DEV_DATABASE_URL")}

# If the flag has been set, configure to use proxy
if os.getenv("USE_CLOUD_SQL_AUTH_PROXY", None):
    DATABASES["default"]["HOST"] = "127.0.0.1"
    DATABASES["default"]["PORT"] = 5434

STATIC_URL = "/static/"
MEDIA_ROOT = Path.joinpath(BASE_DIR, "siteapps", "media")
STATICFILES_DIRS = [Path.joinpath(BASE_DIR, "siteapps", "static")]
