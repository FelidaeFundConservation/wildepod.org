import sys
from pathlib import Path

# Add siteapps to Python path BEFORE any other imports
# This MUST be at the very top of the file, before docstrings and Django imports
_site_apps_dir = Path(__file__).parent / "siteapps"
if str(_site_apps_dir) not in sys.path:
    sys.path.insert(0, str(_site_apps_dir))

"""
Root conftest.py for pytest configuration and shared fixtures.
This file is automatically discovered by pytest and provides fixtures
available to all test files in the project.

IMPORTANT: This file adds siteapps/ to sys.path to enable relative imports
like "from images.models import ..." while keeping Django apps registered
with their dotted paths in INSTALLED_APPS.
"""

import pytest


def pytest_configure(config):
    """
    Hook that runs before Django is set up.
    Add siteapps to Python path to enable relative imports in tests.
    """
    site_apps_dir = Path(__file__).parent / "siteapps"
    if str(site_apps_dir) not in sys.path:
        sys.path.insert(0, str(site_apps_dir))


from django.conf import settings
from django.contrib.auth import get_user_model

# Import factory definitions
from siteapps.conftest_factories import *

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

# ============ Additional Fixtures for View Testing ============

@pytest.fixture
def camera_station(db):
    """Create a basic camera station for testing."""
    from datetime import date
    return CameraStationFactory(date_deployed=date.today())


@pytest.fixture
def complete_camera_station(db):
    """Create a complete camera station with full location hierarchy."""
    from datetime import date
    camera_station = CameraStationFactory(date_deployed=date.today())
    return camera_station


@pytest.fixture
def upload(db, user):
    """Create a basic upload for testing."""
    return UploadFactory(volunteer=user)


@pytest.fixture
def image(db):
    """Create a basic image for testing."""
    return ImageFactory()


@pytest.fixture
def bbox(db, image, user):
    """Create a basic bounding box for testing."""
    annotator = AnnotatorFactory(human=user)
    return BoundingBoxFactory(image=image, created_by=annotator)


@pytest.fixture
def species_name(db):
    """Create a species name for testing."""
    return SpeciesNameFactory(name="Test Species", scientific_name="Testus speciesus")


@pytest.fixture
def category(db):
    """Create a category name for testing (not a Category model instance)."""
    # Return a simple object with a name attribute for tests
    class CategoryName:
        name = "animal"
    return CategoryName()


@pytest.fixture
def activity_type(db):
    """Create an activity type for testing."""
    return ActivityTypeFactory(name="Walking", category="animal")


@pytest.fixture
def expert_user(db):
    """Create an expert user for testing."""
    user = User.objects.create_user(
        email="expert@example.com",
        password="testpass123",
    )
    user.is_expert = True
    user.save()
    Annotator.objects.get_or_create(type="human", human=user)
    return user


@pytest.fixture
def upload_with_images(db):
    """Create an upload with multiple test images."""
    upload = UploadFactory()
    images = [ImageFactory(upload=upload) for _ in range(3)]
    upload.img_count = len(images)
    upload.save()
    return upload


@pytest.fixture
def completed_upload(db, user):
    """Create a completed upload for testing."""
    upload = UploadFactory(volunteer=user, processed=True, upload_complete=True, img_count=10)
    return upload


@pytest.fixture
def image_with_bboxes(db):
    """Create an image with multiple bounding boxes."""
    image = ImageFactory()
    bboxes = [BoundingBoxFactory(image=image) for _ in range(3)]
    for bbox in bboxes:
        CategoryFactory(bounding_box=bbox)
    return image


@pytest.fixture
def annotated_image(db, user):
    """Create a fully annotated image with species and activity."""
    image = ImageFactory()
    annotator = AnnotatorFactory(human=user)
    
    # Add bounding boxes with species and activity
    bbox1 = BoundingBoxFactory(image=image, created_by=annotator)
    CategoryFactory(bounding_box=bbox1, name='animal', created_by=annotator)
    SpeciesFactory(bounding_box=bbox1, created_by=annotator)
    
    bbox2 = BoundingBoxFactory(image=image, created_by=annotator)
    CategoryFactory(bounding_box=bbox2, name='person', created_by=annotator)
    ActivityFactory(bounding_box=bbox2, created_by=annotator)
    
    return image


@pytest.fixture
def mock_dropbox(mocker):
    """Mock Dropbox client for testing upload workflows."""
    mock_client = mocker.MagicMock()
    mocker.patch('images.utils.dropbox_client.create_dropbox_client', return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_storage(mocker):
    """Mock Google Cloud Storage for testing."""
    mock_storage = mocker.MagicMock()
    mocker.patch('images.processors.image.storage', mock_storage)
    return mock_storage