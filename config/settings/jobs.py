"""This is the staging settings that links to a staging database and will be deployed as its own service in within app engine
"""
import google.cloud.logging

from .base import *  # noqa
from .prod import *  # noqa

# SECURITY
# ------------------------------------------------------------------------------
# We can't use Django SECURE_SSL_REDIRECT with manual/basic scaling instances for some reason.
# Therefore we turn it off here but enforce appengine https through the yaml file
SECURE_SSL_REDIRECT = False

# FLAGS DEFINED ONLY FOR EXPORT SERVICE
INSTALLED_APPS.append("siteapps.exports")
EXPORT_SERVICE = True
DEBUG = True
