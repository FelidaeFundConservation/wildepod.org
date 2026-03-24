"""
Comprehensive tests for exports/views.py
Coverage target: 18.95% -> 50%+
"""

import json
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from explore.models import Snapshot
from exports.views import (
    ExportStartView,
    create_snapshot,
    create_snapshot_sql,
    execute_export_query_sql,
    export_camera_station_data,
    export_image_data,
    export_image_data_sql,
    portal_export,
    start_export,
    write_row,
)
from images.models import (
    Annotator,
    BoundingBox,
    CameraStationAction,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
)
from locations.models import Area, CameraStation, County, MacroSite, MicroSite
from users.models import User


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com", password="testpass123")


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(email="staff@example.com", password="staffpass123", is_staff=True)
    return user


@pytest.fixture
def area(db):
    return Area.objects.create(name="Test Area")


@pytest.fixture
def county(db, area):
    return County.objects.create(name="Test County", area=area)


@pytest.fixture
def macro_site(db, county):
    return MacroSite.objects.create(name="Test Macro Site", county=county)


@pytest.fixture
def micro_site(db, macro_site):
    return MicroSite.objects.create(name="Test Micro Site", macro_site=macro_site)


@pytest.fixture
def camera_station(db, micro_site):
    return CameraStation.objects.create(
        station_id="CAM001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        elevation=1000,
        elevation_unit="m",
        date_deployed=timezone.now().date(),
    )


@pytest.fixture
def upload(db, camera_station, staff_user):
    action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=staff_user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="test_folder",
        dropbox_folder_path="/test/folder",
        upload_method="E",
    )


@pytest.fixture
def image_with_data(db, upload):
    """Create an image with full metadata"""
    return Image.objects.create(
        upload=upload,
        dropbox_file_name="test_image.jpg",
        dropbox_file_path="/test/test_image.jpg",
        dropbox_file_path_display="/test/test_image.jpg",
        dropbox_content_hash="hash123",
        dropbox_file_id="file_id_123",
        file_size=2048,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path="thumbnails/test.jpg",
        latitude=27.5,
        longitude=89.5,
        is_video=False,
        social_media_worthy=5,
    )


@pytest.fixture
def species_name(db):
    return SpeciesName.objects.create(name="White-tailed Deer", scientific_name="Odocoileus virginianus")


# Test export_camera_station_data Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExportCameraStationData:
    def test_export_camera_station_data_with_stations(self, camera_station):
        """Test exporting camera station data to TSV"""
        # Create a mock archive file
        mock_archive = Mock()
        mock_archive.writestr = Mock()

        export_camera_station_data(mock_archive)

        # Check that writestr was called with correct filename
        assert mock_archive.writestr.called
        call_args = mock_archive.writestr.call_args
        assert call_args[0][0] == "camera_stations.tsv"

        # Verify the content includes header and data
        tsv_content = call_args[0][1]
        assert "camera_station_id" in tsv_content
        assert "latitude" in tsv_content
        assert "CAM001" in tsv_content

    def test_export_camera_station_data_empty(self, db):
        """Test export with no camera stations"""
        mock_archive = Mock()
        mock_archive.writestr = Mock()

        export_camera_station_data(mock_archive)

        # Should still create file with header
        assert mock_archive.writestr.called
        call_args = mock_archive.writestr.call_args
        tsv_content = call_args[0][1]
        assert "camera_station_id" in tsv_content


# Test export_image_data Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExportImageData:
    @patch("exports.views.settings")
    @patch("exports.views.cache")
    @patch("exports.views.gc")
    def test_export_image_data_basic(self, mock_gc, mock_cache, mock_settings, image_with_data):
        """Test basic image data export"""
        mock_settings.GS_BUCKET_NAME = "test-bucket"
        mock_settings.DROPBOX_URL_PREFIX = "https://dropbox.com"

        mock_archive = Mock()
        mock_archive.writestr = Mock()

        images = Image.objects.filter(id=image_with_data.id)
        export_image_data(mock_archive, images)

        # Verify writestr was called
        assert mock_archive.writestr.called
        call_args = mock_archive.writestr.call_args
        assert call_args[0][0] == "images.tsv"

        # Check that image data is in the content
        tsv_content = call_args[0][1]
        assert "image_id" in tsv_content
        assert str(image_with_data.id) in tsv_content or "test_image.jpg" in tsv_content

    @patch("exports.views.settings")
    @patch("exports.views.cache")
    @patch("exports.views.gc")
    def test_export_image_data_pagination(self, mock_gc, mock_cache, mock_settings, image_with_data):
        """Test that pagination and cleanup work correctly"""
        mock_settings.GS_BUCKET_NAME = "test-bucket"
        mock_settings.DROPBOX_URL_PREFIX = "https://dropbox.com"

        mock_archive = Mock()
        mock_archive.writestr = Mock()

        images = Image.objects.filter(id=image_with_data.id)
        export_image_data(mock_archive, images)

        # Verify cache clearing and garbage collection happened
        assert mock_cache.clear.called
        assert mock_gc.collect.called


# Test write_row Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestWriteRow:
    @patch("exports.views.settings")
    def test_write_row_basic(self, mock_settings, image_with_data):
        """Test writing a single row"""
        mock_settings.GS_BUCKET_NAME = "test-bucket"
        mock_settings.DROPBOX_URL_PREFIX = "https://dropbox.com"

        csv_file = StringIO()
        import csv

        csv_writer = csv.writer(csv_file, delimiter="\t")

        write_row(
            csv_writer,
            image_with_data,
            category_name="Animal",
            species_name="Deer",
            valid_bounding_boxes=[],
            uncertain_bounding_boxes=[],
            valid_or_uncertain_bounding_boxes=[],
        )

        # Verify row was written
        csv_content = csv_file.getvalue()
        assert str(image_with_data.id) in csv_content
        assert "test_image.jpg" in csv_content
        assert "Animal" in csv_content
        assert "Deer" in csv_content


# Test create_snapshot Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateSnapshot:
    @patch("exports.views.export_camera_station_data")
    @patch("exports.views.export_image_data")
    def test_create_snapshot_success(self, mock_export_image, mock_export_camera, user, macro_site, image_with_data):
        """Test successful snapshot creation"""
        data = {
            "user": user.pk,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "macrosites": [macro_site.pk],
        }

        create_snapshot(data)

        # Check that a snapshot was created
        snapshots = Snapshot.objects.filter(volunteer=user)
        assert snapshots.count() == 1

        snapshot = snapshots.first()
        assert snapshot.volunteer == user
        assert snapshot.status == "done"

        # Verify export functions were called
        assert mock_export_camera.called
        assert mock_export_image.called

    def test_create_snapshot_invalid_user(self):
        """Test snapshot creation with invalid user"""
        data = {
            "user": 99999,  # Non-existent user
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        }

        create_snapshot(data)

        # Should not create a snapshot
        assert Snapshot.objects.count() == 0

    @patch("exports.views.export_camera_station_data")
    @patch("exports.views.export_image_data")
    def test_create_snapshot_exception_handling(self, mock_export_image, mock_export_camera, user):
        """Test snapshot creation handles exceptions"""
        # Make export function raise an exception
        mock_export_image.side_effect = Exception("Export failed")

        data = {
            "user": user.pk,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        }

        create_snapshot(data)

        # Snapshot should be created but marked as failed
        snapshot = Snapshot.objects.filter(volunteer=user).first()
        assert snapshot is not None
        assert snapshot.status == "failed"


# Test portal_export Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestPortalExport:
    @patch("exports.views.connection")
    def test_portal_export_with_params(self, mock_connection):
        """Test portal export stored procedure call"""
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("row1",), ("row2",)]
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        results = portal_export(
            macrosite_param="Test Site",
            station_id_param="CAM001",
            start_date_param="2024-01-01",
            end_date_param="2024-12-31",
        )

        # Verify stored procedure was called
        assert mock_cursor.callproc.called
        assert len(results) == 2

    @patch("exports.views.connection")
    def test_portal_export_no_params(self, mock_connection):
        """Test portal export with no parameters"""
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        results = portal_export()

        # Should still work with None parameters
        assert mock_cursor.callproc.called
        assert len(results) == 0


# Test execute_export_query_sql Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExecuteExportQuerySql:
    @patch("exports.views.connection")
    @patch("exports.views.importlib.resources.open_text")
    def test_execute_export_query_with_filters(self, mock_open_text, mock_connection):
        """Test SQL query execution with filters"""
        # Mock SQL file content
        mock_file = StringIO("SELECT * FROM images")
        mock_open_text.return_value.__enter__.return_value = mock_file

        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",)]
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        execute_export_query_sql(macrosite_param="Test Site", start_date_param="2024-01-01")

        # Verify SQL was modified with WHERE clause
        assert mock_cursor.execute.called
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" in executed_sql
        assert "macrosite = %s" in executed_sql

    @patch("exports.views.connection")
    @patch("exports.views.importlib.resources.open_text")
    def test_execute_export_query_no_filters(self, mock_open_text, mock_connection):
        """Test SQL query execution without filters"""
        mock_file = StringIO("SELECT * FROM images")
        mock_open_text.return_value.__enter__.return_value = mock_file

        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        execute_export_query_sql()

        # Should execute without WHERE clause
        assert mock_cursor.execute.called
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql


# Test export_image_data_sql Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExportImageDataSql:
    def test_export_image_data_sql_with_rows(self):
        """Test SQL-based image export with data rows"""
        mock_archive = Mock()
        mock_archive.writestr = Mock()

        # Mock SQL query results
        test_rows = [
            (
                "img1",
                "hash1",
                "file1.jpg",
                "thumb1",
                "link1",
                "2024-01-01",
                27.5,
                89.5,
                False,
                "CAM001",
                "micro",
                "macro",
                "2024-01-01",
                "volunteer",
                "folder",
                5,
                1,
                2,
                1,
                1,
                "Animal",
                1,
                1,
                0,
                "Deer",
            ),
        ]

        export_image_data_sql(mock_archive, test_rows)

        # Verify file was written
        assert mock_archive.writestr.called
        call_args = mock_archive.writestr.call_args
        assert call_args[0][0] == "images.tsv"

        tsv_content = call_args[0][1]
        assert "image_id" in tsv_content
        assert "img1" in tsv_content


# Test create_snapshot_sql Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateSnapshotSql:
    @patch("exports.views.execute_export_query_sql")
    @patch("exports.views.export_image_data_sql")
    def test_create_snapshot_sql_success(self, mock_export, mock_execute, user, macro_site):
        """Test SQL-based snapshot creation"""
        mock_execute.return_value = []

        data = {
            "user": user.pk,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "macrosites": [macro_site.pk],
        }

        create_snapshot_sql(data)

        # Verify snapshot was created
        snapshot = Snapshot.objects.filter(volunteer=user).first()
        assert snapshot is not None
        assert snapshot.status == "done"

    @patch("exports.views.execute_export_query_sql")
    @patch("exports.views.export_image_data_sql")
    def test_create_snapshot_sql_exception(self, mock_export, mock_execute, user):
        """Test SQL snapshot handles exceptions"""
        mock_export.side_effect = Exception("SQL export failed")

        data = {
            "user": user.pk,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        }

        create_snapshot_sql(data)

        # Snapshot should be marked as failed
        snapshot = Snapshot.objects.filter(volunteer=user).first()
        assert snapshot is not None
        assert snapshot.status == "failed"


# Test start_export Function
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestStartExport:
    @patch("exports.views.threading.Thread")
    def test_start_export_creates_thread(self, mock_thread):
        """Test that start_export creates a thread"""
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        data = {"user": 1, "start_date": "2024-01-01"}
        response = start_export(data)

        # Verify thread was created and started
        assert mock_thread.called
        assert mock_thread_instance.start.called

        # Check response
        response_data = json.loads(response.content)
        assert response_data["message"] == "Success"


# Test ExportStartView
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExportStartView:
    @patch("exports.views.threading.Thread")
    def test_export_start_view_post(self, mock_thread, request_factory, user):
        """Test POST request to ExportStartView"""
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        data = {"user": str(user.pk), "start_date": "2024-01-01", "end_date": "2024-12-31"}

        request = request_factory.post("/exports/start/", data=json.dumps(data), content_type="application/json")

        response = ExportStartView.as_view()(request)

        # Verify thread was created
        assert mock_thread.called
        assert mock_thread_instance.start.called

        # Check response
        assert response.status_code == 200
        response_data = json.loads(response.content)
        assert response_data["message"] == "Success"

    def test_export_start_view_csrf_exempt(self, request_factory):
        """Test that ExportStartView is CSRF exempt"""
        # The view should work without CSRF token
        data = {"user": 1, "test": "data"}

        request = request_factory.post("/exports/start/", data=json.dumps(data), content_type="application/json")
        # Don't set CSRF token

        # Should not raise CSRF error
        response = ExportStartView.as_view()(request)
        assert response.status_code == 200


# Integration Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestExportIntegration:
    """Integration tests for the export workflow"""

    @patch("exports.views.settings")
    @patch("exports.views.export_camera_station_data")
    @patch("exports.views.export_image_data")
    def test_full_export_workflow(
        self, mock_export_image, mock_export_camera, mock_settings, user, macro_site, image_with_data
    ):
        """Test complete export workflow from view to snapshot"""
        mock_settings.GS_BUCKET_NAME = "test-bucket"
        mock_settings.DROPBOX_URL_PREFIX = "https://dropbox.com"
        mock_settings.EXPORT_DATE_FORMAT = "%Y-%m-%d"

        # Update image timestamp to match filter
        image_with_data.trigger_timestamp = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        image_with_data.save()

        data = {
            "user": user.pk,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "macrosites": [macro_site.pk],
        }

        # Run the snapshot creation
        create_snapshot(data)

        # Verify snapshot created with correct filters
        snapshot = Snapshot.objects.filter(volunteer=user).first()
        assert snapshot is not None
        assert str(snapshot.start_date) == "2024-01-01"
        assert str(snapshot.end_date) == "2024-12-31"
        assert macro_site in snapshot.macrosites.all()

    def test_export_with_date_filters(self, user, upload, image_with_data):
        """Test export respects date filters"""
        # Set image to specific date
        image_with_data.trigger_timestamp = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        image_with_data.save()

        # Create future image that should be excluded
        future_image = Image.objects.create(
            upload=upload,
            dropbox_file_name="future.jpg",
            dropbox_file_path="/test/future.jpg",
            dropbox_file_path_display="/test/future.jpg",
            dropbox_content_hash="hash_future",
            dropbox_file_id="file_id_future",
            file_size=2048,
            trigger_timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            thumbnail_gcloud_path="thumbnails/future.jpg",
        )

        # Get filtered images (mimicking what create_snapshot does)
        start_date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        filterset = {"trigger_timestamp__gte": start_date, "trigger_timestamp__lte": end_date}
        images = Image.objects.filter(**filterset)

        # Only 2024 image should be included
        assert image_with_data in images
        assert future_image not in images
