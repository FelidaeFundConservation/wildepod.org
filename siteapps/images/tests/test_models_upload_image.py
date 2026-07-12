# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Test cases for image models (Upload, Image, and related models).
"""
import pytest
import uuid
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from images.models import CameraStationAction, TimeCorrection, Upload, Image
from locations.models import Area, County, MacroSite, MicroSite, Grid, CameraStation


@pytest.fixture
def camera_station(db, user):
    """Create a test camera station."""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro = MacroSite.objects.create(name="Test Macro", county=county)
    micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
    
    return CameraStation.objects.create(
        station_id="CAM-TEST-001",
        latitude=37.7749,
        longitude=-122.4194,
        micro_site=micro,
        date_deployed=timezone.now().date()
    )


@pytest.fixture
def camera_action(db):
    """Create a camera station action."""
    return CameraStationAction.objects.create(action="Retrieved SD Card")


@pytest.mark.django_db
class TestCameraStationActionModel:
    """Test CameraStationAction model."""

    def test_action_creation(self):
        """Test creating a CameraStationAction."""
        action = CameraStationAction.objects.create(action="Camera Deployed")
        assert action.action == "Camera Deployed"
        assert action.pk is not None

    def test_action_str_representation(self):
        """Test CameraStationAction string representation."""
        action = CameraStationAction.objects.create(action="Battery Replaced")
        assert str(action) == "Battery Replaced"

    def test_action_ordering(self):
        """Test actions are ordered by created date (descending)."""
        action1 = CameraStationAction.objects.create(action="First Action")
        action2 = CameraStationAction.objects.create(action="Second Action")
        action3 = CameraStationAction.objects.create(action="Third Action")
        
        actions = list(CameraStationAction.objects.all())
        # Should be ordered by created time (most recent first)
        assert actions[0] == action3
        assert actions[1] == action2
        assert actions[2] == action1


@pytest.mark.django_db
class TestTimeCorrectionModel:
    """Test TimeCorrection model."""

    def test_time_correction_creation_minimal(self):
        """Test creating a TimeCorrection with minimal fields."""
        correction = TimeCorrection.objects.create()
        
        assert correction.years == 0
        assert correction.months == 0
        assert correction.days == 0
        assert correction.hours == 0
        assert correction.minutes == 0
        assert correction.pk is not None

    def test_time_correction_creation_full(self):
        """Test creating a TimeCorrection with all fields."""
        start = timezone.now()
        end = start + timedelta(days=30)
        daylight = start.date()
        applied = timezone.now()
        
        correction = TimeCorrection.objects.create(
            years=0,
            months=0,
            days=5,
            hours=2,
            minutes=30,
            start_date=start,
            end_date=end,
            daylight_savings=daylight,
            applied_at=applied
        )
        
        assert correction.days == 5
        assert correction.hours == 2
        assert correction.minutes == 30
        assert correction.start_date == start
        assert correction.end_date == end
        assert correction.daylight_savings == daylight
        assert correction.applied_at == applied

    def test_time_correction_negative_values(self):
        """Test TimeCorrection accepts negative values for offsets."""
        correction = TimeCorrection.objects.create(
            days=-10,
            hours=-5,
            minutes=-30
        )
        
        assert correction.days == -10
        assert correction.hours == -5
        assert correction.minutes == -30


@pytest.mark.django_db
class TestUploadModel:
    """Test Upload model."""

    def test_upload_creation_minimal(self, camera_station, camera_action, user):
        """Test creating an Upload with minimal required fields."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user,
            dropbox_folder_name="test_folder_001",
            dropbox_folder_path="/test/folder_001",
            dropbox_request_id="req_001",
            dropbox_request_url="https://dropbox.com/request/001"
        )
        
        assert upload.id is not None  # UUID is generated
        assert isinstance(upload.id, uuid.UUID)
        assert upload.camera_station == camera_station
        assert upload.last_action == camera_action
        assert upload.volunteer == user
        assert upload.img_count == 0  # Default value
        assert upload.time_correction is None
        assert not upload.data_sheet  # FileField is empty

    def test_upload_with_data_sheet(self, camera_station, camera_action, user):
        """Test Upload with attached data sheet."""
        test_file = SimpleUploadedFile("datasheet.xlsx", b"file_content", content_type="application/vnd.ms-excel")
        
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user,
            data_sheet=test_file,
            img_count=150,
            dropbox_folder_name="test_folder_002",
            dropbox_folder_path="/test/folder_002",
            dropbox_request_id="req_002",
            dropbox_request_url="https://dropbox.com/request/002"
        )
        
        assert upload.data_sheet.name.startswith("data_sheets/")
        assert upload.img_count == 150
        # File should be renamed to upload id
        assert str(upload.id) in upload.data_sheet.name

    def test_upload_with_time_correction(self, camera_station, camera_action, user):
        """Test Upload with time correction."""
        correction = TimeCorrection.objects.create(hours=2, minutes=30)
        
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user,
            time_correction=correction,
            dropbox_folder_name="test_folder_004",
            dropbox_folder_path="/test/folder_004",
            dropbox_request_id="req_004",
            dropbox_request_url="https://dropbox.com/request/004"
        )
        
        assert upload.time_correction == correction

    def test_upload_with_time_error_details(self, camera_station, camera_action, user):
        """Test Upload with time error details."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user,
            dropbox_folder_name="test_folder_003",
            dropbox_folder_path="/test/folder_003",
            dropbox_request_id="req_003",
            dropbox_request_url="https://dropbox.com/request/003",
            time_error_details="Camera clock was off by 2 hours"
        )
        
        assert upload.time_error_details == "Camera clock was off by 2 hours"


@pytest.mark.django_db
class TestImageModel:
    """Test Image model."""

    def test_image_creation_minimal(self, camera_station, camera_action, user):
        """Test creating an Image with minimal required fields."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/uploads/IMG_001.JPG",
            dropbox_file_path_display="/uploads/IMG_001.JPG",
            dropbox_content_hash="abc123" * 10,  # 64 char hash
            dropbox_file_id="id:abc123",
            file_size=2048000
        )
        
        assert image.id is not None  # UUID is generated
        assert isinstance(image.id, uuid.UUID)
        assert image.upload == upload
        assert image.dropbox_file_name == "IMG_001.JPG"
        assert image.file_size == 2048000
        assert image.is_video is False  # Default
        assert image.processed is False  # Default
        assert image.deleted is False  # Default

    def test_image_video_flag(self, camera_station, camera_action, user):
        """Test Image with is_video flag."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        video = Image.objects.create(
            upload=upload,
            dropbox_file_name="VID_001.MP4",
            dropbox_file_path="/uploads/VID_001.MP4",
            dropbox_file_path_display="/uploads/VID_001.MP4",
            dropbox_content_hash="def456" * 10,
            dropbox_file_id="id:def456",
            file_size=10240000,
            is_video=True,
            duration=120  # 2 minutes
        )
        
        assert video.is_video is True
        assert video.duration == 120

    def test_image_with_metadata(self, camera_station, camera_action, user):
        """Test Image with full metadata."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        trigger_time = timezone.now()
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/uploads/IMG_002.JPG",
            dropbox_file_path_display="/uploads/IMG_002.JPG",
            dropbox_content_hash="ghi789" * 10,
            dropbox_file_id="id:ghi789",
            file_size=3072000,
            trigger_timestamp=trigger_time,
            height=1080,
            width=1920,
            latitude=37.7749,
            longitude=-122.4194,
            processed=True
        )
        
        assert image.trigger_timestamp == trigger_time
        assert image.height == 1080
        assert image.width == 1920
        assert image.latitude == 37.7749
        assert image.longitude == -122.4194
        assert image.processed is True

    def test_image_precomputed_flags(self, camera_station, camera_action, user):
        """Test Image precomputed pipeline flags."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_003.JPG",
            dropbox_file_path="/uploads/IMG_003.JPG",
            dropbox_file_path_display="/uploads/IMG_003.JPG",
            dropbox_content_hash="jkl012" * 10,
            dropbox_file_id="id:jkl012",
            file_size=2560000,
            category_pipeline_complete=True,
            species_pipeline_complete=True,
            activity_pipeline_complete=True,
            has_animals=True,
            has_wild_animals=True,
            has_cats=True,
            has_bbox_above_confidence_threshold=True,
            use_precomputed_flags=True
        )
        
        assert image.category_pipeline_complete is True
        assert image.species_pipeline_complete is True
        assert image.activity_pipeline_complete is True
        assert image.has_animals is True
        assert image.has_wild_animals is True
        assert image.has_cats is True
        assert image.has_bbox_above_confidence_threshold is True
        assert image.use_precomputed_flags is True
        assert image.has_humans is False
        assert image.has_vehicles is False

    def test_image_review_flags(self, camera_station, camera_action, user):
        """Test Image staff review and report flags."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_004.JPG",
            dropbox_file_path="/uploads/IMG_004.JPG",
            dropbox_file_path_display="/uploads/IMG_004.JPG",
            dropbox_content_hash="mno345" * 10,
            dropbox_file_id="id:mno345",
            file_size=2048000,
            staff_review_needed=True,
            image_reported=True
        )
        
        assert image.staff_review_needed is True
        assert image.image_reported is True

    def test_image_str_representation(self, camera_station, camera_action, user):
        """Test Image string representation."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="DSC_0123.JPG",
            dropbox_file_path="/uploads/DSC_0123.JPG",
            dropbox_file_path_display="/uploads/DSC_0123.JPG",
            dropbox_content_hash="pqr678" * 10,
            dropbox_file_id="id:pqr678",
            file_size=2048000
        )
        
        assert str(image) == "DSC_0123.JPG"

    def test_image_upload_relationship(self, camera_station, camera_action, user):
        """Test Image-Upload relationship."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        image1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/uploads/IMG_001.JPG",
            dropbox_file_path_display="/uploads/IMG_001.JPG",
            dropbox_content_hash="aaa111" * 10,
            dropbox_file_id="id:aaa111",
            file_size=2048000
        )
        
        image2 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/uploads/IMG_002.JPG",
            dropbox_file_path_display="/uploads/IMG_002.JPG",
            dropbox_content_hash="bbb222" * 10,
            dropbox_file_id="id:bbb222",
            file_size=2048000
        )
        
        # Check that upload has multiple images
        assert image1 in upload.images.all()
        assert image2 in upload.images.all()
        assert upload.images.count() == 2

    def test_image_static_methods(self, camera_station, camera_action, user):
        """Test Image static utility methods."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_action,
            volunteer=user
        )
        
        # Create some test images
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/uploads/IMG_001.JPG",
            dropbox_file_path_display="/uploads/IMG_001.JPG",
            dropbox_content_hash="ccc333" * 10,
            dropbox_file_id="id:ccc333",
            file_size=2048000,
            processed=True
        )
        
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/uploads/IMG_002.JPG",
            dropbox_file_path_display="/uploads/IMG_002.JPG",
            dropbox_content_hash="ddd444" * 10,
            dropbox_file_id="id:ddd444",
            file_size=2048000,
            processed=False
        )
        
        # Test static methods
        assert Image.get_total_images() == 2
        assert Image.get_total_images_processed() == 1
        assert Image.get_total_images_not_processed() == 1
