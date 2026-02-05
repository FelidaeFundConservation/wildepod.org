"""
Tests for images image processor functions.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.utils import timezone

from images.models import (
    Annotator, Bot, BoundingBox, Category, Image, Upload
)
from images.processors.image import (
    has_bbox_above_confidence_threshold,
    MEGADETECTOR_LABEL_MAP,
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


@pytest.fixture
def image(db, upload):
    """Create an image for testing."""
    return Image.objects.create(
        upload=upload,
        dropbox_file_name="test.jpg",
        dropbox_file_path="/test/path/test.jpg",
        dropbox_file_path_display="/test/path/test.jpg",
        dropbox_content_hash="abc123",
        dropbox_file_id="file_id_123",
        file_size=1024,
        processed=True,
    )


@pytest.fixture
def bot(db):
    """Create a bot for testing."""
    return Bot.objects.create(name="MegaDetector", version="v5.0")


@pytest.fixture
def ml_annotator(db, bot):
    """Create an ML annotator for testing."""
    return Annotator.objects.create(type="bot", bot=bot)


@pytest.mark.django_db
class TestHasBboxAboveConfidenceThreshold:
    """Test has_bbox_above_confidence_threshold function."""
    
    def test_image_with_bbox_above_threshold(self, image, ml_annotator):
        """Test image with bounding box above confidence threshold."""
        BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        result = has_bbox_above_confidence_threshold(image)
        assert result is True
        
    def test_image_with_bbox_below_threshold(self, image, ml_annotator):
        """Test image with bounding box below confidence threshold."""
        BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.5,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        result = has_bbox_above_confidence_threshold(image)
        assert result is False
        
    def test_image_without_bbox(self, image):
        """Test image without any bounding boxes."""
        result = has_bbox_above_confidence_threshold(image)
        assert result is False
        
    def test_image_with_invalid_bbox(self, image, ml_annotator):
        """Test image with invalid bounding box."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
            validity="INVALID"
        )
        
        result = has_bbox_above_confidence_threshold(image)
        assert result is False
        
    def test_image_with_multiple_bboxes(self, image, ml_annotator):
        """Test image with multiple bounding boxes."""
        # One above threshold
        BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.3,
            h=0.3,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        # One below threshold
        BoundingBox.objects.create(
            image=image,
            x=0.5,
            y=0.5,
            w=0.3,
            h=0.3,
            confidence=0.6,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        result = has_bbox_above_confidence_threshold(image)
        assert result is True


@pytest.mark.django_db
class TestMegadetectorLabelMap:
    """Test MEGADETECTOR_LABEL_MAP constant."""
    
    def test_label_map_contains_expected_values(self):
        """Test that label map has correct mappings."""
        assert MEGADETECTOR_LABEL_MAP == {
            "1": "animal",
            "2": "person",
            "3": "vehicle"
        }
        
    def test_label_map_animal(self):
        """Test animal label mapping."""
        assert MEGADETECTOR_LABEL_MAP["1"] == "animal"
        
    def test_label_map_person(self):
        """Test person label mapping."""
        assert MEGADETECTOR_LABEL_MAP["2"] == "person"
        
    def test_label_map_vehicle(self):
        """Test vehicle label mapping."""
        assert MEGADETECTOR_LABEL_MAP["3"] == "vehicle"


@pytest.mark.django_db
class TestAddThumbnail:
    """Test add_thumbnail function."""
    
    @patch('images.processors.image.create_dropbox_client')
    def test_add_thumbnail_without_dropbox_client(self, mock_create_client, image):
        """Test thumbnail addition when dropbox client is not configured."""
        from images.processors.image import add_thumbnail
        
        mock_create_client.return_value = None
        
        # Should handle gracefully when no dropbox client
        add_thumbnail(image)
        
        # Should not crash and return None
        assert image.thumbnail_gcloud_path is None or image.thumbnail_gcloud_path == ""


@pytest.mark.django_db
class TestRunModelInference:
    """Test run_model_inference function."""
    
    @patch('images.processors.image.http')
    def test_run_model_inference_creates_bot_if_not_exists(self, mock_http, image):
        """Test that inference creates bot object if it doesn't exist."""
        from images.processors.image import run_model_inference
        
        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "detections": []
        }
        mock_http.post.return_value = mock_response
        
        # Ensure bot doesn't exist
        Bot.objects.filter(name="MegaDetector", version="v5a.0.0").delete()
        
        initial_count = Bot.objects.count()
        
        # This will create the bot (or try to)
        # The function may fail due to missing dependencies but bot creation should work
        try:
            run_model_inference(image)
        except Exception:
            pass  # Expected to fail due to missing cloud function setup
        
        # Check if bot was created or already existed
        assert Bot.objects.filter(name="MegaDetector").exists()
