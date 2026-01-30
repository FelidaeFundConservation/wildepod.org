"""
Application entry point template for custom GCP App Engine deployments.

This is a TEMPLATE file. When using deploy_custom.sh, this file will be
auto-generated with your custom environment name.

PLACEHOLDERS TO REPLACE:
- <env-name> → Your environment name in lowercase-hyphen format (e.g., my-dev)

DO NOT COMMIT: Custom environment files should be added to .gitignore

This file imports the WSGI application from config.wsgi.<env-name> and exposes
it as 'app' for Gunicorn to use. Referenced in <env-name>.yaml entrypoint.
"""

from config.wsgi.<env-name> import application

# Expose application as 'app' for Gunicorn
# The entrypoint in app.yaml will be: gunicorn -t 2400 -b :$PORT <env-name>:app
app = application
