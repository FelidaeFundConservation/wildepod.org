# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Test cases for image signals.
"""
import pytest
from datetime import datetime
from django.utils import timezone

from images.models import CameraStationAction, Upload, Image
from locations.models import Area, County, MacroSite, MicroSite, CameraStation


@pytest.fixture
def upload(db, user):
    """Create a test upload."""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro = MacroSite.objects.create(name="Test Macro", county=county)
    micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
    station = CameraStation.objects.create(
        station_id="CAM-SIGNAL-001",
        latitude=37.7749,
        longitude=-122.4194,
        micro_site=micro,
        date_deployed=timezone.now().date()
    )
    action = CameraStationAction.objects.create(action="Test Action")
    
    return Upload.objects.create(
        camera_station=station,
        date_retrieved=timezone.now(),
        last_action=action,
        volunteer=user,
        dropbox_folder_name="signal_test_folder",
        dropbox_folder_path="/signal/test/folder",
        dropbox_request_id="signal_req_001",
        dropbox_request_url="https://dropbox.com/request/signal001"
    )


@pytest.mark.django_db
class TestImageSignals:
    """Test image-related signals."""

    def test_image_creation_increments_upload_img_count(self, upload):
        """Test that creating an Image increments Upload.img_count."""
        # Initial count should be 0
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 0
        assert upload.processed_img_count == 0
        assert upload.camera_station.total_img_count == 0
        assert upload.camera_station.processed_img_count == 0
        assert upload.camera_station.micro_site.macro_site.total_img_count == 0
        assert upload.camera_station.micro_site.macro_site.processed_img_count == 0
        
        # Create first image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test/IMG_001.JPG",
            dropbox_file_path_display="/test/IMG_001.JPG",
            dropbox_content_hash="abc123" * 10,
            dropbox_file_id="id:abc123",
            file_size=2048000
        )
        
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 1
        assert upload.processed_img_count == 0
        assert upload.camera_station.total_img_count == 1
        assert upload.camera_station.processed_img_count == 0
        assert upload.camera_station.micro_site.macro_site.total_img_count == 1
        assert upload.camera_station.micro_site.macro_site.processed_img_count == 0
        
        # Create second image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/test/IMG_002.JPG",
            dropbox_file_path_display="/test/IMG_002.JPG",
            dropbox_content_hash="def456" * 10,
            dropbox_file_id="id:def456",
            file_size=2048000
        )
        
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 2
        assert upload.processed_img_count == 0
        assert upload.camera_station.total_img_count == 2
        assert upload.camera_station.micro_site.macro_site.total_img_count == 2

    def test_image_deletion_decrements_upload_img_count(self, upload):
        """Test that deleting an Image decrements Upload.img_count."""
        # Create 3 images
        img1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test/IMG_001.JPG",
            dropbox_file_path_display="/test/IMG_001.JPG",
            dropbox_content_hash="aaa111" * 10,
            dropbox_file_id="id:aaa111",
            file_size=2048000
        )
        img2 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/test/IMG_002.JPG",
            dropbox_file_path_display="/test/IMG_002.JPG",
            dropbox_content_hash="bbb222" * 10,
            dropbox_file_id="id:bbb222",
            file_size=2048000
        )
        img3 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_003.JPG",
            dropbox_file_path="/test/IMG_003.JPG",
            dropbox_file_path_display="/test/IMG_003.JPG",
            dropbox_content_hash="ccc333" * 10,
            dropbox_file_id="id:ccc333",
            file_size=2048000
        )
        
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 3
        assert upload.camera_station.total_img_count == 3
        assert upload.camera_station.micro_site.macro_site.total_img_count == 3
        
        # Delete one image
        img1.delete()
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 2
        assert upload.camera_station.total_img_count == 2
        assert upload.camera_station.micro_site.macro_site.total_img_count == 2
        
        # Delete another image
        img2.delete()
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 1
        assert upload.camera_station.total_img_count == 1
        assert upload.camera_station.micro_site.macro_site.total_img_count == 1
        
        # Delete last image
        img3.delete()
        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()
        assert upload.img_count == 0
        assert upload.camera_station.total_img_count == 0
        assert upload.camera_station.micro_site.macro_site.total_img_count == 0

    def test_processed_updates_increment_cached_processed_counts(self, upload):
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test/IMG_001.JPG",
            dropbox_file_path_display="/test/IMG_001.JPG",
            dropbox_content_hash="ppp111" * 10,
            dropbox_file_id="id:ppp111",
            file_size=2048000,
        )

        image.processed = True
        image.save()

        upload.refresh_from_db()
        upload.camera_station.refresh_from_db()
        upload.camera_station.micro_site.macro_site.refresh_from_db()

        assert upload.processed_img_count == 1
        assert upload.camera_station.processed_img_count == 1
        assert upload.camera_station.micro_site.macro_site.processed_img_count == 1

    def test_upload_deleted_flag_syncs_to_images(self, upload):
        """Test that Upload.deleted flag syncs to related Images."""
        # Create images
        img1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test/IMG_001.JPG",
            dropbox_file_path_display="/test/IMG_001.JPG",
            dropbox_content_hash="ddd444" * 10,
            dropbox_file_id="id:ddd444",
            file_size=2048000
        )
        img2 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/test/IMG_002.JPG",
            dropbox_file_path_display="/test/IMG_002.JPG",
            dropbox_content_hash="eee555" * 10,
            dropbox_file_id="id:eee555",
            file_size=2048000
        )
        
        # Initially, deleted should be False
        assert upload.deleted is False
        assert img1.deleted is False
        assert img2.deleted is False
        
        # Set upload.deleted = True and save
        upload.deleted = True
        upload.save()
        
        # Images should now have deleted=True
        img1.refresh_from_db()
        img2.refresh_from_db()
        assert img1.deleted is True
        assert img2.deleted is True

    def test_upload_undeleted_flag_syncs_to_images(self, upload):
        """Test that un-deleting Upload syncs to Images."""
        # Create images with deleted=True
        img1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test/IMG_001.JPG",
            dropbox_file_path_display="/test/IMG_001.JPG",
            dropbox_content_hash="fff666" * 10,
            dropbox_file_id="id:fff666",
            file_size=2048000,
            deleted=True
        )
        
        upload.deleted = True
        upload.save()
        
        img1.refresh_from_db()
        assert img1.deleted is True
        
        # Un-delete the upload
        upload.deleted = False
        upload.save()
        
        img1.refresh_from_db()
        assert img1.deleted is False

    def test_multiple_uploads_independent_counts(self, upload, user):
        """Test that img_count is independent per upload."""
        # Create second upload
        area = Area.objects.create(name="Test Area 2")
        county = County.objects.create(name="Test County 2", area=area)
        macro = MacroSite.objects.create(name="Test Macro 2", county=county)
        micro = MicroSite.objects.create(name="Test Micro 2", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM-SIGNAL-002",
            latitude=37.7749,
            longitude=-122.4194,
            micro_site=micro,
            date_deployed=timezone.now().date()
        )
        action = CameraStationAction.objects.create(action="Test Action 2")
        
        upload2 = Upload.objects.create(
            camera_station=station,
            date_retrieved=timezone.now(),
            last_action=action,
            volunteer=user,
            dropbox_folder_name="signal_test_folder_2",
            dropbox_folder_path="/signal/test/folder2",
            dropbox_request_id="signal_req_002",
            dropbox_request_url="https://dropbox.com/request/signal002"
        )
        
        # Add images to first upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_001.JPG",
            dropbox_file_path="/test1/IMG_001.JPG",
            dropbox_file_path_display="/test1/IMG_001.JPG",
            dropbox_content_hash="ggg777" * 10,
            dropbox_file_id="id:ggg777",
            file_size=2048000
        )
        Image.objects.create(
            upload=upload,
            dropbox_file_name="IMG_002.JPG",
            dropbox_file_path="/test1/IMG_002.JPG",
            dropbox_file_path_display="/test1/IMG_002.JPG",
            dropbox_content_hash="hhh888" * 10,
            dropbox_file_id="id:hhh888",
            file_size=2048000
        )
        
        # Add images to second upload
        Image.objects.create(
            upload=upload2,
            dropbox_file_name="IMG_003.JPG",
            dropbox_file_path="/test2/IMG_003.JPG",
            dropbox_file_path_display="/test2/IMG_003.JPG",
            dropbox_content_hash="iii999" * 10,
            dropbox_file_id="id:iii999",
            file_size=2048000
        )
        
        # Check counts are independent
        upload.refresh_from_db()
        upload2.refresh_from_db()
        assert upload.img_count == 2
        assert upload2.img_count == 1
