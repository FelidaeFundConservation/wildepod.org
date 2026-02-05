"""
Root conftest.py for pytest configuration and shared fixtures.
This file is automatically discovered by pytest and provides fixtures
available to all test files in the project.

IMPORTANT: This file adds siteapps/ to sys.path to enable relative imports
like "from images.models import ..." while keeping Django apps registered
with their dotted paths in INSTALLED_APPS.
"""
import sys
from pathlib import Path

# Add siteapps to Python path BEFORE any Django imports
# This must happen before pytest_django tries to set up Django
site_apps_dir = Path(__file__).parent / "siteapps"
if str(site_apps_dir) not in sys.path:
    sys.path.insert(0, str(site_apps_dir))

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture(autouse=True)
def disable_whitenoise_compression(settings):
    """
    Disable WhiteNoise's CompressedManifestStaticFilesStorage during tests.
    This prevents "Missing staticfiles manifest entry" errors when testing views
    that render templates with static files.
    """
    settings.STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"


@pytest.fixture
def user(db):
    """Create a regular user for testing."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    """Create a staff user for testing."""
    return User.objects.create_user(
        email="staffuser@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def superuser(db):
    """Create a superuser for testing."""
    return User.objects.create_superuser(
        email="admin@example.com",
        password="testpass123",
    )


@pytest.fixture
def client():
    """Django test client."""
    from django.test import Client
    return Client()


@pytest.fixture
def authenticated_client(user, client):
    """Client with authenticated user."""
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(staff_user, client):
    """Client with authenticated staff user."""
    client.force_login(staff_user)
    return client


@pytest.fixture
def admin_client(superuser, client):
    """Client with authenticated superuser."""
    client.force_login(superuser)
    return client


@pytest.fixture(autouse=True)
def media_storage(settings, tmpdir):
    """Use temporary directory for media files during tests."""
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture(autouse=True)
def email_backend_setup(settings):
    """Use locmem email backend for testing."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
