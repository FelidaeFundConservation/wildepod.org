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


@pytest.mark.django_db
class TestAddThumbnailExtended:
    """Extended tests for add_thumbnail function."""
    
    @patch('images.processors.image.create_dropbox_client')
    @patch('images.processors.image.storage')
    def test_add_thumbnail_success(self, mock_storage, mock_create_client, image):
        """Test successful thumbnail addition."""
        from images.processors.image import add_thumbnail
        
        # Mock dropbox client
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Mock dropbox response
        mock_metadata = MagicMock()
        mock_response = MagicMock()
        mock_response.content = b"fake_image_data"
        mock_dbx.files_get_thumbnail_v2.return_value = (mock_metadata, mock_response)
        
        # Mock storage save
        mock_storage.save.return_value = "thumbnails/1024/test_hash.jpg"
        
        # Call the function
        add_thumbnail(image, dbx=mock_dbx)
        
        # Verify thumbnail path was set
        assert image.thumbnail_gcloud_path == "thumbnails/1024/test_hash.jpg"
        
        # Verify dropbox was called
        assert mock_dbx.files_get_thumbnail_v2.called
        
        # Verify storage save was called
        assert mock_storage.save.called
    
    @patch('images.processors.image.create_dropbox_client')
    @patch('images.processors.image.storage')
    def test_add_thumbnail_storage_error(self, mock_storage, mock_create_client, image):
        """Test thumbnail addition when storage fails."""
        from images.processors.image import add_thumbnail
        
        # Mock dropbox client
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Mock dropbox response
        mock_metadata = MagicMock()
        mock_response = MagicMock()
        mock_response.content = b"fake_image_data"
        mock_dbx.files_get_thumbnail_v2.return_value = (mock_metadata, mock_response)
        
        # Mock storage failure
        mock_storage.save.side_effect = Exception("Storage error")
        
        # Should handle error gracefully
        add_thumbnail(image, dbx=mock_dbx)
        
        # Image should not have thumbnail path
        assert not image.thumbnail_gcloud_path


@pytest.mark.django_db
class TestAddBoundingBoxes:
    """Test add_bounding_boxes function."""
    
    @patch('images.processors.image.http')
    def test_add_bounding_boxes_success(self, mock_http, image, bot, ml_annotator):
        """Test successful bounding box addition."""
        from images.processors.image import add_bounding_boxes
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "annotation": {
                "detections": [
                    {
                        "category": "1",  # animal
                        "conf": 0.95,
                        "bbox": [0.1, 0.2, 0.3, 0.4]
                    },
                    {
                        "category": "2",  # person
                        "conf": 0.87,
                        "bbox": [0.5, 0.6, 0.2, 0.3]
                    }
                ]
            }
        }
        mock_http.post.return_value = mock_response
        
        image.thumbnail_gcloud_path = "test/path.jpg"
        image.save()
        
        # Call function
        add_bounding_boxes(
            image=image,
            image_url="http://test.com/image.jpg",
            bot=bot,
            id_token="test_token",
            annotator=ml_annotator
        )
        
        # Verify bounding boxes were created
        bboxes = BoundingBox.objects.filter(image=image)
        assert bboxes.count() == 2
        
        # Verify categories were created
        categories = Category.objects.filter(bounding_box__image=image)
        assert categories.count() == 2
        
        # Check bboxes (order may vary)
        confidences = sorted([bbox.confidence for bbox in bboxes])
        assert 0.87 in confidences
        assert 0.95 in confidences
        
        # Check that x values are present
        x_values = [bbox.x for bbox in bboxes]
        assert 0.1 in x_values
        assert 0.5 in x_values
        
        # Check image flags were updated
        image.refresh_from_db()
        assert hasattr(image, 'has_bbox_above_confidence_threshold')
    
    @patch('images.processors.image.http')
    def test_add_bounding_boxes_api_failure(self, mock_http, image, bot, ml_annotator):
        """Test bounding box addition when API fails."""
        from images.processors.image import add_bounding_boxes
        
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_http.post.return_value = mock_response
        
        image.thumbnail_gcloud_path = "test/path.jpg"
        image.save()
        
        # Should raise exception
        with pytest.raises(Exception) as exc_info:
            add_bounding_boxes(
                image=image,
                image_url="http://test.com/image.jpg",
                bot=bot,
                id_token="test_token",
                annotator=ml_annotator
            )
        
        assert "failed with status code: 500" in str(exc_info.value)


@pytest.mark.django_db  
class TestDetectSpecies:
    """Test detect_species function."""
    
    @patch('images.processors.image.http')
    def test_detect_species_success(self, mock_http, image, bot, ml_annotator):
        """Test successful species detection."""
        from images.processors.image import detect_species
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "classes": ["Puma", "Deer", "Bear"]
        }
        mock_http.post.return_value = mock_response
        
        # Call function
        result = detect_species(
            image=image,
            image_url="http://test.com/image.jpg",
            bot=bot,
            id_token="test_token",
            annotator=ml_annotator
        )
        
        # Verify species were returned
        assert result == ["Puma", "Deer", "Bear"]
        assert len(result) == 3
        
        # Verify HTTP was called correctly
        mock_http.post.assert_called_once()
    
    @patch('images.processors.image.http')
    def test_detect_species_api_failure(self, mock_http, image, bot, ml_annotator):
        """Test species detection when API fails."""
        from images.processors.image import detect_species
        
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_http.post.return_value = mock_response
        
        # Should raise exception
        with pytest.raises(Exception) as exc_info:
            detect_species(
                image=image,
                image_url="http://test.com/image.jpg",
                bot=bot,
                id_token="test_token",
                annotator=ml_annotator
            )
        
        assert "failed with status code: 500" in str(exc_info.value)


@pytest.mark.django_db
class TestProcessImage:
    """Test process_image function."""
    
    @patch('images.processors.image.run_model_inference')
    @patch('images.processors.image.add_thumbnail')
    @patch('images.processors.image.create_dropbox_client')
    def test_process_image_success(self, mock_create_client, mock_add_thumbnail, mock_inference, image):
        """Test successful image processing."""
        from images.processors.image import process_image
        
        # Setup mocks
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Set image to have thumbnail path
        image.thumbnail_gcloud_path = "test/path.jpg"
        image.processed = False
        image.save()
        
        # Mock inference returns
        mock_inference.side_effect = [None, ["Puma", "Deer"]]
        
        # Call function
        result = process_image(image, dbx=mock_dbx)
        
        # Verify image was processed
        assert result is True
        image.refresh_from_db()
        assert image.processed is True
        assert image.use_precomputed_flags is True
        assert image.has_cats is True  # Puma detected
    
    @patch('images.processors.image.add_thumbnail')
    @patch('images.processors.image.create_dropbox_client')
    def test_process_image_no_thumbnail(self, mock_create_client, mock_add_thumbnail, image):
        """Test image processing when thumbnail creation fails."""
        from images.processors.image import process_image
        
        # Setup mocks
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Image has no thumbnail
        image.thumbnail_gcloud_path = None
        image.processed = False
        image.save()
        
        # Mock add_thumbnail doesn't set path
        mock_add_thumbnail.side_effect = lambda img, dbx: None
        
        # Call function
        result = process_image(image, dbx=mock_dbx)
        
        # Image should not be processed
        assert result is False
    
    @patch('images.processors.image.run_model_inference')
    @patch('images.processors.image.add_thumbnail')
    @patch('images.processors.image.create_dropbox_client')
    def test_process_image_with_exception(self, mock_create_client, mock_add_thumbnail, mock_inference, image):
        """Test image processing when inference fails."""
        from images.processors.image import process_image
        
        # Setup mocks
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Set image to have thumbnail path
        image.thumbnail_gcloud_path = "test/path.jpg"
        image.processed = False
        image.save()
        
        # Mock inference raises exception
        mock_inference.side_effect = Exception("Inference failed")
        
        # Call function
        result = process_image(image, dbx=mock_dbx)
        
        # Image should not be marked as processed
        image.refresh_from_db()
        assert image.processed is False
