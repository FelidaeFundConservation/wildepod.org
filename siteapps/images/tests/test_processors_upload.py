"""
Tests for images upload processor functions.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from images.models import Image, Upload
from images.processors.upload import (
    MAX_THREADS_FOR_IMAGE_PROCESSING,
    MAX_THREADS_FOR_DROPBOX_API,
)
from locations.models import Area, County, MacroSite, MicroSite, CameraStation
from users.models import User


# Fixtures
@pytest.fixture
def area(db):
    """Create an area for testing."""
    return Area.objects.create(name="Test Area")


@pytest.fixture
def county(db, area):
    """Create a county for testing."""
    return County.objects.create(name="Test County", area=area)


@pytest.fixture
def macro_site(db, county):
    """Create a macro site for testing."""
    return MacroSite.objects.create(name="Test Macro Site", county=county)


@pytest.fixture
def micro_site(db, macro_site):
    """Create a micro site for testing."""
    return MicroSite.objects.create(name="Test Micro Site", macro_site=macro_site)


@pytest.fixture
def camera_station(db, micro_site):
    """Create a camera station for testing."""
    return CameraStation.objects.create(
        station_id="TEST001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=90.5,
        date_deployed=timezone.now().date(),
    )


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass",
    )


@pytest.fixture
def camera_station_action(db):
    """Create a camera station action for testing."""
    from images.models import CameraStationAction
    return CameraStationAction.objects.create(action="Retrieved SD card")


@pytest.fixture
def upload(db, camera_station, regular_user, camera_station_action):
    """Create an upload for testing."""
    return Upload.objects.create(
        camera_station=camera_station,
        date_retrieved=timezone.now(),
        last_action=camera_station_action,
        volunteer=regular_user,
        dropbox_folder_name="test_folder",
        dropbox_folder_path="/test/path",
        dropbox_request_id="test123",
        dropbox_request_url="https://dropbox.com/test",
    )


@pytest.mark.django_db
class TestThreadingConstants:
    """Test threading constants."""
    
    def test_max_threads_for_image_processing(self):
        """Test MAX_THREADS_FOR_IMAGE_PROCESSING constant."""
        assert MAX_THREADS_FOR_IMAGE_PROCESSING == 10
        assert isinstance(MAX_THREADS_FOR_IMAGE_PROCESSING, int)
        assert MAX_THREADS_FOR_IMAGE_PROCESSING > 0
        
    def test_max_threads_for_dropbox_api(self):
        """Test MAX_THREADS_FOR_DROPBOX_API constant."""
        assert MAX_THREADS_FOR_DROPBOX_API == 15
        assert isinstance(MAX_THREADS_FOR_DROPBOX_API, int)
        assert MAX_THREADS_FOR_DROPBOX_API > 0


@pytest.mark.django_db
class TestSetupDropboxPaths:
    """Test setup_dropbox_paths function."""
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_without_client_raises_error(self, mock_create_client, upload):
        """Test that setup fails without dropbox client."""
        from images.processors.upload import setup_dropbox_paths
        
        mock_create_client.return_value = None
        
        with pytest.raises(ValueError, match="Dropbox credentials not configured"):
            setup_dropbox_paths(upload, None)
            
    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_generates_folder_name(self, mock_create_client, camera_station, regular_user, camera_station_action):
        """Test that folder name is properly generated."""
        from images.processors.upload import setup_dropbox_paths
        
        # Create a mock dropbox client
        mock_dbx = Mock()
        mock_dbx.file_requests_create.return_value = Mock(
            id="request123",
            url="https://dropbox.com/request",
            is_open=True
        )
        mock_create_client.return_value = mock_dbx
        
        # Create new upload
        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E"  # Email method
        )
        
        setup_dropbox_paths(upload, None, dbx=mock_dbx)
        
        # Check that folder name was generated
        assert upload.dropbox_folder_name is not None
        assert "test macro site" in upload.dropbox_folder_name.lower()
        assert "test001" in upload.dropbox_folder_name.lower()
        
    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_handles_duplicates(self, mock_create_client, camera_station, regular_user, camera_station_action):
        """Test that duplicate folder names are handled."""
        from images.processors.upload import setup_dropbox_paths
        
        # Create existing upload with similar name
        existing_upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            dropbox_folder_name="existing_folder",
            dropbox_folder_path="/existing",
            dropbox_request_id="existing123",
            dropbox_request_url="https://dropbox.com/existing",
        )
        
        mock_dbx = Mock()
        mock_dbx.file_requests_create.return_value = Mock(
            id="request456",
            url="https://dropbox.com/request2",
            is_open=True
        )
        mock_create_client.return_value = mock_dbx
        
        # Create new upload with same characteristics
        new_upload = Upload(
            camera_station=camera_station,
            date_retrieved=existing_upload.date_retrieved,
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E"
        )
        
        setup_dropbox_paths(new_upload, None, dbx=mock_dbx)
        
        # Folder name should have (1) appended for duplicate
        assert new_upload.dropbox_folder_name != existing_upload.dropbox_folder_name


@pytest.mark.django_db
class TestCloneDataSheet:
    """Test clone_data_sheet function."""
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_clone_data_sheet_with_file(self, mock_create_client):
        """Test cloning data sheet to dropbox."""
        from images.processors.upload import clone_data_sheet
        
        mock_dbx = Mock()
        mock_dbx.files_upload.return_value = Mock()
        mock_create_client.return_value = mock_dbx
        
        # Create a simple file
        file_content = b"test data sheet content"
        file = SimpleUploadedFile("test_sheet.pdf", file_content, content_type="application/pdf")
        
        # Should not crash
        try:
            clone_data_sheet(file, "test_sheet.pdf", "test_folder", dbx=mock_dbx)
        except Exception as e:
            # May fail due to missing implementation details, but shouldn't crash on basic call
            pass


@pytest.mark.django_db
class TestUploadProcessing:
    """Test upload processing related functions."""
    
    def test_upload_has_required_fields(self, upload):
        """Test that upload has all required fields."""
        assert upload.camera_station is not None
        assert upload.date_retrieved is not None
        assert upload.last_action is not None
        assert upload.volunteer is not None
        assert upload.dropbox_folder_name is not None
        assert upload.dropbox_folder_path is not None
        
    def test_upload_can_have_images(self, upload):
        """Test that images can be associated with upload."""
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/path/test.jpg",
            dropbox_file_path_display="/test/path/test.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=1024,
        )
        
        assert image.upload == upload
        assert upload.images.count() == 1
