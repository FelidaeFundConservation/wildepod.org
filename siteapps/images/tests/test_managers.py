# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Additional test cases for image models - managers and static methods.
"""
import pytest
from django.utils import timezone

from images.models import (
    CameraStationAction, Upload, Image, Annotator,
    BoundingBox, Category, SpeciesName
)
from locations.models import Area, County, MacroSite, MicroSite, CameraStation


@pytest.fixture
def upload_with_images(db, user):
    """Create an upload with multiple images."""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro = MacroSite.objects.create(name="Test Macro", county=county)
    micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
    station = CameraStation.objects.create(
        station_id="CAM-MGR-001",
        latitude=37.7749,
        longitude=-122.4194,
        micro_site=micro,
        date_deployed=timezone.now().date()
    )
    action = CameraStationAction.objects.create(action="Retrieved SD Card")
    
    upload = Upload.objects.create(
        camera_station=station,
        date_retrieved=timezone.now(),
        last_action=action,
        volunteer=user,
        dropbox_folder_name="manager_test_folder",
        dropbox_folder_path="/manager/test/folder",
        dropbox_request_id="mgr_req_001",
        dropbox_request_url="https://dropbox.com/request/mgr001"
    )
    
    # Create images
    img1 = Image.objects.create(
        upload=upload,
        dropbox_file_name="IMG_001.JPG",
        dropbox_file_path="/test/IMG_001.JPG",
        dropbox_file_path_display="/test/IMG_001.JPG",
        dropbox_content_hash="mgr111" * 10,
        dropbox_file_id="id:mgr111",
        file_size=2048000,
        processed=True
    )
    
    img2 = Image.objects.create(
        upload=upload,
        dropbox_file_name="IMG_002.JPG",
        dropbox_file_path="/test/IMG_002.JPG",
        dropbox_file_path_display="/test/IMG_002.JPG",
        dropbox_content_hash="mgr222" * 10,
        dropbox_file_id="id:mgr222",
        file_size=2048000,
        processed=False
    )
    
    img3 = Image.objects.create(
        upload=upload,
        dropbox_file_name="IMG_003.JPG",
        dropbox_file_path="/test/IMG_003.JPG",
        dropbox_file_path_display="/test/IMG_003.JPG",
        dropbox_content_hash="mgr333" * 10,
        dropbox_file_id="id:mgr333",
        file_size=2048000,
        processed=True
    )
    
    return upload, [img1, img2, img3]


@pytest.mark.django_db
class TestImageStaticMethods:
    """Test Image static methods."""

    def test_get_total_images(self, upload_with_images):
        """Test get_total_images method."""
        upload, images = upload_with_images
        
        total = Image.get_total_images()
        assert total == 3

    def test_get_total_images_processed(self, upload_with_images):
        """Test get_total_images_processed method."""
        upload, images = upload_with_images
        
        total_processed = Image.get_total_images_processed()
        assert total_processed == 2  # img1 and img3 are processed

    def test_get_total_images_not_processed(self, upload_with_images):
        """Test get_total_images_not_processed method."""
        upload, images = upload_with_images
        
        total_not_processed = Image.get_total_images_not_processed()
        assert total_not_processed == 1  # Only img2 is not processed

    def test_get_total_images_empty_database(self):
        """Test static methods with empty database."""
        assert Image.get_total_images() == 0
        assert Image.get_total_images_processed() == 0
        assert Image.get_total_images_not_processed() == 0


@pytest.mark.django_db
class TestImageManager:
    """Test ImageManager methods."""

    def test_annotated_queryset(self, upload_with_images):
        """Test annotated() manager method."""
        upload, images = upload_with_images
        
        # Get annotated queryset
        annotated_images = Image.objects.annotated()
        
        # Check that annotation fields are present
        for img in annotated_images:
            assert hasattr(img, 'num_objects')
            assert hasattr(img, 'num_bbox_checked_by')
            assert hasattr(img, 'num_species_checked_by')
            assert hasattr(img, 'num_activity_checked_by')
            
            # Initial values should be 0
            assert img.num_objects == 0
            assert img.num_bbox_checked_by == 0
            assert img.num_species_checked_by == 0
            assert img.num_activity_checked_by == 0

    def test_image_str_method(self, upload_with_images):
        """Test Image __str__ method."""
        upload, images = upload_with_images
        
        assert str(images[0]) == "IMG_001.JPG"
        assert str(images[1]) == "IMG_002.JPG"
        assert str(images[2]) == "IMG_003.JPG"


@pytest.mark.django_db
class TestUploadOrdering:
    """Test Upload model ordering."""

    def test_upload_ordering_by_created(self, user):
        """Test that uploads are ordered by -created."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM-ORDER-001",
            latitude=37.7749,
            longitude=-122.4194,
            micro_site=micro,
            date_deployed=timezone.now().date()
        )
        action = CameraStationAction.objects.create(action="Test Action")
        
        # Create uploads with different dates
        upload1 = Upload.objects.create(
            camera_station=station,
            date_retrieved=timezone.now(),
            last_action=action,
            volunteer=user,
            dropbox_folder_name="folder_1",
            dropbox_folder_path="/test/folder_1",
            dropbox_request_id="req_1",
            dropbox_request_url="https://dropbox.com/request/1"
        )
        
        upload2 = Upload.objects.create(
            camera_station=station,
            date_retrieved=timezone.now(),
            last_action=action,
            volunteer=user,
            dropbox_folder_name="folder_2",
            dropbox_folder_path="/test/folder_2",
            dropbox_request_id="req_2",
            dropbox_request_url="https://dropbox.com/request/2"
        )
        
        upload3 = Upload.objects.create(
            camera_station=station,
            date_retrieved=timezone.now(),
            last_action=action,
            volunteer=user,
            dropbox_folder_name="folder_3",
            dropbox_folder_path="/test/folder_3",
            dropbox_request_id="req_3",
            dropbox_request_url="https://dropbox.com/request/3"
        )
        
        # Get all uploads
        uploads = list(Upload.objects.all())
        
        # Should be ordered by -created (newest first)
        assert uploads[0] == upload3
        assert uploads[1] == upload2
        assert uploads[2] == upload1

    def test_upload_str_method(self, user):
        """Test Upload __str__ method."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM-STR-001",
            latitude=37.7749,
            longitude=-122.4194,
            micro_site=micro,
            date_deployed=timezone.now().date()
        )
        action = CameraStationAction.objects.create(action="Test Action")
        
        upload = Upload.objects.create(
            camera_station=station,
            date_retrieved=timezone.now(),
            last_action=action,
            volunteer=user,
            dropbox_folder_name="my_test_folder",
            dropbox_folder_path="/test/my_test_folder",
            dropbox_request_id="req_str",
            dropbox_request_url="https://dropbox.com/request/str"
        )
        
        assert str(upload) == "my_test_folder"
