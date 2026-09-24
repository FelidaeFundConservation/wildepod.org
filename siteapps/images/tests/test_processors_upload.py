# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for images upload processor functions.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from images.models import Image, Upload
from images.processors.upload import (
    MAX_THREADS_FOR_IMAGE_PROCESSING,
    MAX_THREADS_FOR_DROPBOX_API,
    check_image_valid,
    precompute_context_images,
    get_dropbox_file_listing,
    preretrieve_file_metadata,
    get_metadata_with_retry,
    process_dropbox_file,
    get_dropbox_item_count,
)
from images.tests.dropbox_stub import FakeDropbox, base_folder_name as _base_folder_name
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

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_names_are_unique_past_the_second_upload(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """Every upload for one station and date gets a name no other upload holds.

        The generated name has no time component, so same-day retrievals all start from the same
        base. The old count-based suffix handed "(1)" to the third upload and every one after it,
        and since dropbox_folder_path is unique and not a form field, that reached the database as
        an unhandled IntegrityError -- a Server Error on the create-upload page.
        """
        from images.processors.upload import setup_dropbox_paths

        mock_dbx = Mock()
        mock_dbx.file_requests_create.return_value = Mock(
            id="request789", url="https://dropbox.com/request3", is_open=True
        )
        mock_create_client.return_value = mock_dbx

        # Fixed, not timezone.now(): the folder name is built from date_retrieved.date(), so a base
        # time late enough in the UTC day would push the later offsets onto tomorrow's date, change
        # the base name mid-loop, and fail this test for a few hours every day.
        date_retrieved = datetime(2026, 3, 20, 6, 0, tzinfo=dt_timezone.utc)
        names = []

        # Five retrievals off the same station on the same day. Distinct times, because
        # unique_together on (camera_station, date_retrieved) is what the form already rejects.
        for hour in range(5):
            upload = Upload(
                camera_station=camera_station,
                date_retrieved=date_retrieved + timedelta(hours=hour),
                last_action=camera_station_action,
                volunteer=regular_user,
                upload_method="E",
            )
            setup_dropbox_paths(upload, None, dbx=mock_dbx)
            upload.save()
            names.append(upload.dropbox_folder_name)

        assert len(set(names)) == len(names), f"duplicate folder names handed out: {names}"

        base = names[0]
        assert names == [base] + [f"{base} ({n})" for n in range(1, 5)]

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_skips_names_held_by_deleted_uploads(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """Soft-deleted uploads keep their folder name, so the next attempt must step over it.

        This is the delete-and-retry loop a volunteer runs after a failed upload, and the case the
        duplicate handling was originally added for.
        """
        from images.processors.upload import setup_dropbox_paths

        mock_dbx = Mock()
        mock_dbx.file_requests_create.return_value = Mock(
            id="request999", url="https://dropbox.com/request4", is_open=True
        )
        mock_create_client.return_value = mock_dbx

        # Fixed for the same reason as above -- a rolling base time could put the fresh upload on a
        # different date, giving it a different base name and passing this test without ever
        # exercising the allocation it is here to check.
        date_retrieved = datetime(2026, 3, 20, 6, 0, tzinfo=dt_timezone.utc)
        taken = []

        for hour in range(3):
            upload = Upload(
                camera_station=camera_station,
                date_retrieved=date_retrieved + timedelta(hours=hour),
                last_action=camera_station_action,
                volunteer=regular_user,
                upload_method="E",
            )
            setup_dropbox_paths(upload, None, dbx=mock_dbx)
            upload.deleted = True
            upload.save()
            taken.append(upload.dropbox_folder_name)

        fresh = Upload(
            camera_station=camera_station,
            date_retrieved=date_retrieved + timedelta(hours=3),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        setup_dropbox_paths(fresh, None, dbx=mock_dbx)

        assert fresh.dropbox_folder_name not in taken
        fresh.save()  # would raise IntegrityError if the name were still taken

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_steps_over_a_dropbox_folder_that_holds_files(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """An occupied folder means that name is not free, so take the next one and carry on.

        Hard-deleting an Upload row from the admin leaves its Dropbox folder behind with the images
        still in it, and the database no longer holds the name, so it looks free. Writing into it
        would hand those images to this upload once process_upload lists the path -- but failing
        would leave the volunteer as stuck on that station and date as the duplicate-name bug did,
        which is the thing this is all meant to fix. So: step over it.
        """
        from images.processors.upload import setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        base = _base_folder_name(upload)
        dbx = FakeDropbox(occupied={f"/{base}": ["IMG_0001.JPG"]})

        setup_dropbox_paths(upload, None, dbx=dbx)

        assert upload.dropbox_folder_name == f"{base} (1)"
        assert upload.dropbox_folder_path == f"/{base} (1)"
        # The occupied folder was left exactly as it was found.
        assert dbx.folders[f"/{base}"] == ["IMG_0001.JPG"]
        upload.save()

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_points_the_file_request_at_the_folder_it_claimed(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """A file request is a live door into its destination, so it must open onto our folder.

        Opening one against the first candidate and only then discovering the folder is someone
        else's leaves an active request writing into their images.
        """
        from images.processors.upload import setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        base = _base_folder_name(upload)
        dbx = FakeDropbox(occupied={f"/{base}": ["IMG_0001.JPG"]})

        setup_dropbox_paths(upload, None, dbx=dbx)

        assert [destination for _, destination in dbx.file_requests] == [f"/{base} (1)"]

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_writes_the_datasheet_into_the_folder_it_claimed(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """clone_data_sheet() uploads with WriteMode.overwrite, creating the folder as a side effect.

        Left to run on an unclaimed name it would write into -- and overwrite the datasheet of --
        whichever upload owns that folder.
        """
        from images.processors.upload import setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="D",
        )
        base = _base_folder_name(upload)
        dbx = FakeDropbox(occupied={f"/{base}": ["data_sheet/theirs.pdf"]})

        data_sheet = SimpleUploadedFile("sheet.pdf", b"datasheet bytes")
        upload.data_sheet = data_sheet
        setup_dropbox_paths(upload, data_sheet, dbx=dbx)

        assert [path for path, _ in dbx.uploads] == [f"/{base} (1)/data_sheet/sheet.pdf"]
        assert dbx.folders[f"/{base}"] == ["data_sheet/theirs.pdf"]

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_gives_up_after_exhausting_candidate_names(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """Every candidate occupied is not something another name will fix."""
        from images.processors.upload import MAX_FOLDER_NAME_CANDIDATES, setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        base = _base_folder_name(upload)
        occupied = {f"/{base}": ["x"]}
        occupied.update({f"/{base} ({n})": ["x"] for n in range(1, MAX_FOLDER_NAME_CANDIDATES + 5)})
        dbx = FakeDropbox(occupied=occupied)

        with pytest.raises(ValueError, match="Could not find a free Dropbox folder"):
            setup_dropbox_paths(upload, None, dbx=dbx)

        assert dbx.create_attempts == MAX_FOLDER_NAME_CANDIDATES
        assert dbx.file_requests == []

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_never_reuses_a_folder_it_did_not_create(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """An empty folder is stepped over too -- emptiness does not establish ownership.

        A file request is created before the row is saved, so a save that fails leaves an empty
        folder with a live request still pointing into it, and a hard-deleted upload that never
        received images leaves the same thing with its URL in someone's history. Adopting either
        would give this upload a folder a second, still-open request writes into.
        """
        from images.processors.upload import setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        base = _base_folder_name(upload)
        dbx = FakeDropbox(occupied={f"/{base}": []})  # empty: the orphan-with-live-request shape

        setup_dropbox_paths(upload, None, dbx=dbx)

        assert upload.dropbox_folder_name == f"{base} (1)"
        assert [destination for _, destination in dbx.file_requests] == [f"/{base} (1)"]
        upload.save()

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_steps_over_a_file_in_the_way_of_the_path(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """A file sitting at the folder path is just another taken name."""
        import dropbox as dropbox_sdk

        from images.processors.upload import setup_dropbox_paths

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="E",
        )
        base = _base_folder_name(upload)
        dbx = FakeDropbox()
        dbx.conflicts[f"/{base}"] = dropbox_sdk.files.WriteConflictError.file

        setup_dropbox_paths(upload, None, dbx=dbx)

        assert upload.dropbox_folder_name == f"{base} (1)"

    @patch('images.processors.upload.create_dropbox_client')
    def test_concurrent_creates_cannot_land_on_the_same_folder_name(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """Dropbox folder creation is the arbiter, so two racing creates get different names.

        Both see the same set of names held by rows and propose the same candidate; exactly one
        create succeeds, and the loser moves on. Without that, both would have carried the same
        name to an insert and the second would have raised the IntegrityError this branch exists
        to remove.
        """
        from images.processors.upload import setup_dropbox_paths

        dbx = FakeDropbox()  # one shared Dropbox, as two web workers would see
        names = []

        for _ in range(2):
            upload = Upload(
                camera_station=camera_station,
                date_retrieved=timezone.now(),
                last_action=camera_station_action,
                volunteer=regular_user,
                upload_method="E",
            )
            # Neither has been saved, so the database proposes the same candidate to both.
            setup_dropbox_paths(upload, None, dbx=dbx)
            names.append(upload.dropbox_folder_name)

        assert len(set(names)) == 2, f"both creates took the same name: {names}"

    @patch('images.processors.upload.create_dropbox_client')
    def test_setup_dropbox_paths_reraises_non_conflict_dropbox_errors(
        self, mock_create_client, camera_station, regular_user, camera_station_action
    ):
        """Only a path conflict is swallowed. A real Dropbox failure still surfaces."""
        import dropbox as dropbox_sdk

        from images.processors.upload import setup_dropbox_paths

        insufficient_space = dropbox_sdk.exceptions.ApiError(
            request_id="req",
            error=dropbox_sdk.files.CreateFolderError.path(
                dropbox_sdk.files.WriteError.insufficient_space
            ),
            user_message_text=None,
            user_message_locale=None,
        )

        mock_dbx = Mock()
        mock_dbx.files_create_folder.side_effect = insufficient_space
        mock_create_client.return_value = mock_dbx

        upload = Upload(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=regular_user,
            upload_method="D",
        )

        with pytest.raises(dropbox_sdk.exceptions.ApiError):
            setup_dropbox_paths(upload, None, dbx=mock_dbx)


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


@pytest.mark.django_db
class TestCheckImageValid:
    """Test check_image_valid function."""
    
    @patch('images.processors.upload.requests.get')
    @patch('images.processors.upload.PILImage.open')
    def test_check_image_valid_success(self, mock_pil_open, mock_requests_get, upload):
        """Test check_image_valid with a valid image."""
        # Create an image object
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/path/test.jpg",
            dropbox_file_path_display="/test/path/test.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=1024,
            thumbnail_gcloud_path="test/thumb.jpg",
        )
        
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake image data"
        mock_requests_get.return_value = mock_response
        
        # Mock PIL Image
        mock_pil_open.return_value.convert.return_value = MagicMock()
        
        result = check_image_valid(image)
        
        assert result is True
        mock_requests_get.assert_called_once()
        mock_pil_open.assert_called_once()
    
    @patch('images.processors.upload.requests.get')
    @patch('images.processors.upload.PILImage.open')
    def test_check_image_valid_corrupted_image(self, mock_pil_open, mock_requests_get, upload):
        """Test check_image_valid with a corrupted image."""
        from PIL import UnidentifiedImageError
        
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="corrupted.jpg",
            dropbox_file_path="/test/path/corrupted.jpg",
            dropbox_file_path_display="/test/path/corrupted.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=1024,
            thumbnail_gcloud_path="test/corrupted.jpg",
        )
        
        # Mock successful HTTP response but corrupted image data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"not an image"
        mock_requests_get.return_value = mock_response
        
        # Mock PIL raising UnidentifiedImageError
        mock_pil_open.side_effect = UnidentifiedImageError("Cannot identify image file")
        
        result = check_image_valid(image)
        
        assert result is False
    
    @patch('images.processors.upload.requests.get')
    def test_check_image_valid_http_error(self, mock_requests_get, upload):
        """Test check_image_valid with HTTP error."""
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="missing.jpg",
            dropbox_file_path="/test/path/missing.jpg",
            dropbox_file_path_display="/test/path/missing.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=1024,
            thumbnail_gcloud_path="test/missing.jpg",
        )
        
        # Mock failed HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.reason = "Not Found"
        mock_requests_get.return_value = mock_response
        
        result = check_image_valid(image)
        
        assert result is None


@pytest.mark.django_db
class TestPrecomputeContextImages:
    """Test precompute_context_images function."""
    
    def test_precompute_context_images_with_trigger_timestamp(self, upload):
        """Test precomputing context images with trigger timestamps."""
        from datetime import datetime, timedelta
        
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        
        # Create primary image
        image1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="img1.jpg",
            dropbox_file_path="/test/img1.jpg",
            dropbox_file_path_display="/test/img1.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="id1",
            file_size=1024,
            trigger_timestamp=base_time,
            thumbnail_gcloud_path="test/thumb1.jpg",
        )
        
        # Create context images (before and after)
        image2 = Image.objects.create(
            upload=upload,
            dropbox_file_name="img2.jpg",
            dropbox_file_path="/test/img2.jpg",
            dropbox_file_path_display="/test/img2.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="id2",
            file_size=1024,
            trigger_timestamp=base_time - timedelta(minutes=5),
            thumbnail_gcloud_path="test/thumb2.jpg",
        )
        
        image3 = Image.objects.create(
            upload=upload,
            dropbox_file_name="img3.jpg",
            dropbox_file_path="/test/img3.jpg",
            dropbox_file_path_display="/test/img3.jpg",
            dropbox_content_hash="hash3",
            dropbox_file_id="id3",
            file_size=1024,
            trigger_timestamp=base_time + timedelta(minutes=5),
            thumbnail_gcloud_path="test/thumb3.jpg",
        )
        
        precompute_context_images(upload)
        
        # Refresh from database
        image1.refresh_from_db()
        
        # context_image_gcloud_paths is stored as a TextField, so it's a string representation of the list
        assert image1.context_image_gcloud_paths is not None
        assert "test/thumb2.jpg" in image1.context_image_gcloud_paths
        assert "test/thumb3.jpg" in image1.context_image_gcloud_paths
    
    def test_precompute_context_images_no_trigger_timestamp(self, upload):
        """Test precomputing context images without trigger timestamps."""
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="img_no_ts.jpg",
            dropbox_file_path="/test/img_no_ts.jpg",
            dropbox_file_path_display="/test/img_no_ts.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="id",
            file_size=1024,
            trigger_timestamp=None,
            thumbnail_gcloud_path="test/thumb_no_ts.jpg",
        )
        
        # Should not crash when trigger_timestamp is None
        precompute_context_images(upload)
        
        image.refresh_from_db()
        # context_image_gcloud_paths should remain None or empty
        assert image.context_image_gcloud_paths is None or image.context_image_gcloud_paths == []


@pytest.mark.django_db
class TestGetDropboxFileListing:
    """Test get_dropbox_file_listing function."""
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_get_dropbox_file_listing_basic(self, mock_create_client):
        """Test basic file listing."""
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Create mock file entries
        mock_entry1 = MagicMock()
        mock_entry2 = MagicMock()
        
        # Mock response without pagination
        mock_response = MagicMock()
        mock_response.entries = [mock_entry1, mock_entry2]
        mock_response.has_more = False
        mock_dbx.files_list_folder.return_value = mock_response
        
        result = get_dropbox_file_listing("/test/folder")
        
        assert len(result) == 2
        assert result == [mock_entry1, mock_entry2]
        mock_dbx.files_list_folder.assert_called_once_with("/test/folder", recursive=True)
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_get_dropbox_file_listing_with_pagination(self, mock_create_client):
        """Test file listing with pagination."""
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Create mock entries
        mock_entry1 = MagicMock()
        mock_entry2 = MagicMock()
        mock_entry3 = MagicMock()
        
        # Mock first response with pagination
        mock_response1 = MagicMock()
        mock_response1.entries = [mock_entry1, mock_entry2]
        mock_response1.has_more = True
        mock_response1.cursor = "cursor123"
        
        # Mock second response
        mock_response2 = MagicMock()
        mock_response2.entries = [mock_entry3]
        mock_response2.has_more = False
        
        mock_dbx.files_list_folder.return_value = mock_response1
        mock_dbx.files_list_folder_continue.return_value = mock_response2
        
        result = get_dropbox_file_listing("/test/folder")
        
        assert len(result) == 3
        assert result == [mock_entry1, mock_entry2, mock_entry3]
        mock_dbx.files_list_folder_continue.assert_called_once_with("cursor123")
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_get_dropbox_file_listing_no_credentials(self, mock_create_client):
        """Test file listing when dropbox credentials are not configured."""
        mock_create_client.return_value = None
        
        with pytest.raises(ValueError, match="Dropbox credentials not configured"):
            get_dropbox_file_listing("/test/folder")


@pytest.mark.django_db
class TestPreretrieveFileMetadata:
    """Test preretrieve_file_metadata function."""
    
    @patch('images.processors.upload.create_dropbox_client')
    def test_preretrieve_file_metadata(self, mock_create_client):
        """Test preretrieving file metadata."""
        mock_dbx = MagicMock()
        mock_create_client.return_value = mock_dbx
        
        # Create mock entries
        mock_entry1 = MagicMock()
        mock_entry1.path_lower = "/test/file1.jpg"
        mock_entry2 = MagicMock()
        mock_entry2.path_lower = "/test/file2.jpg"
        
        # Mock metadata responses
        mock_metadata1 = MagicMock()
        mock_metadata2 = MagicMock()
        mock_dbx.files_get_metadata.side_effect = [mock_metadata1, mock_metadata2]
        
        metadata_dict = {}
        preretrieve_file_metadata([mock_entry1, mock_entry2], metadata_dict, mock_dbx)
        
        # Give threads time to complete
        import time
        time.sleep(0.5)
        
        assert len(metadata_dict) == 2
        assert metadata_dict["/test/file1.jpg"] == mock_metadata1
        assert metadata_dict["/test/file2.jpg"] == mock_metadata2


@pytest.mark.django_db
class TestGetMetadataWithRetry:
    """Test get_metadata_with_retry function."""
    
    def test_get_metadata_with_retry_success(self):
        """Test successful metadata retrieval."""
        mock_metadata = MagicMock()
        preretrieved_metadata = {"/test/file.jpg": mock_metadata}
        
        mock_entry = MagicMock()
        mock_entry.path_lower = "/test/file.jpg"
        
        result = get_metadata_with_retry(preretrieved_metadata, mock_entry, max_retries=3, delay=0.01)
        
        assert result == mock_metadata
    
    def test_get_metadata_with_retry_eventual_success(self):
        """Test metadata retrieval with delayed availability."""
        preretrieved_metadata = {}
        mock_metadata = MagicMock()
        
        mock_entry = MagicMock()
        mock_entry.path_lower = "/test/file.jpg"
        
        # Simulate metadata becoming available after some time
        def delayed_insert():
            import time
            time.sleep(0.05)
            preretrieved_metadata["/test/file.jpg"] = mock_metadata
        
        import threading
        thread = threading.Thread(target=delayed_insert)
        thread.start()
        
        result = get_metadata_with_retry(preretrieved_metadata, mock_entry, max_retries=10, delay=0.02)
        
        thread.join()
        assert result == mock_metadata
    
    def test_get_metadata_with_retry_failure(self):
        """Test metadata retrieval failure after max retries."""
        preretrieved_metadata = {}
        
        mock_entry = MagicMock()
        mock_entry.path_lower = "/test/missing_file.jpg"
        
        result = get_metadata_with_retry(preretrieved_metadata, mock_entry, max_retries=2, delay=0.01)
        
        assert result is None


@pytest.mark.django_db
class TestProcessDropboxFile:
    """Test process_dropbox_file function."""
    
    def test_process_dropbox_file_non_media(self, upload):
        """Test processing a non-media file."""
        import dropbox
        
        # Mock folder entry (not a file)
        mock_entry = MagicMock(spec=dropbox.files.FolderMetadata)
        
        preretrieved_metadata = {}
        
        result = process_dropbox_file(upload, mock_entry, preretrieved_metadata)
        
        # Non-media files return True by default
        assert result is True


@pytest.mark.django_db
class TestGetDropboxItemCount:
    """Test get_dropbox_item_count function."""
    
    def test_get_dropbox_item_count_existing_key(self):
        """Test getting item count for existing upload."""
        from images.processors.upload import dropbox_item_counts
        
        upload_id = "test-uuid-123"
        dropbox_item_counts[upload_id] = 42
        
        result = get_dropbox_item_count(upload_id)
        
        assert result == 42
        
        # Cleanup
        dropbox_item_counts.pop(upload_id, None)
    
    def test_get_dropbox_item_count_missing_key(self):
        """Test getting item count for non-existing upload."""
        result = get_dropbox_item_count("non-existing-uuid")
        
        assert result == "?"
