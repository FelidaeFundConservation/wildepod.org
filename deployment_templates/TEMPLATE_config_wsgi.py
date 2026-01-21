"""
WSGI config template for custom GCP App Engine deployments.

This is a TEMPLATE file. When using deploy_custom.sh, this file will be
auto-generated with your custom environment name.

PLACEHOLDERS TO REPLACE:
- <env-name> → Your environment name in lowercase-hyphen format (e.g., my-dev)

DO NOT COMMIT: Custom environment files should be added to .gitignore

This module contains the WSGI application used by Django's development server
and any production WSGI deployments. It exposes a module-level variable named
``application``.
"""

import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

# Add siteapps directory to Python path
# This allows easy placement of apps within the interior siteapps directory.
ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
sys.path.append(str(ROOT_DIR / "siteapps"))

# Set Django settings module
# We defer to a DJANGO_SETTINGS_MODULE already in the environment. This breaks
# if running multiple sites in the same mod_wsgi process. To fix this, use
# mod_wsgi daemon mode with each site in its own daemon process.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.<env-name>")

# Get WSGI application
# This application object is used by any WSGI server configured to use this
# file. This includes Django's development server, if the WSGI_APPLICATION
# setting points here.
application = get_wsgi_application()

# Apply WSGI middleware here if needed
# Example:
# from helloworld.wsgi import HelloWorldApplication
# application = HelloWorldApplication(application)
