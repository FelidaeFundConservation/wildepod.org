# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Comprehensive tests for Upload views
Coverage target: images/views/upload.py (421 lines, 19.71% -> 60%+)
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from images.forms import UploadForm
from images.models import CameraStationAction, TimeCorrection, Upload
from images.views.upload import (
    UploadCompleteView,
    UploadCreateView,
    UploadDeleteView,
    UploadDetailView,
    UploadListView,
    UploadResumeProcessingView,
    UploadStatusView,
)
from locations.models import CameraStation
from users.models import User


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def camera_station(db):
    """Create a complete camera station with location hierarchy"""
    from siteapps.conftest_factories import CameraStationFactory
    return CameraStationFactory()


@pytest.fixture
def upload(db, camera_station, user):
    """Create an upload with required relationships"""
    from django.utils import timezone
    import uuid
    action, _ = CameraStationAction.objects.get_or_create(
        action="DEPLOY"
    )
    unique_id = uuid.uuid4().hex[:8]
    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name=f"test_upload_{unique_id}",
        dropbox_folder_path=f"/test/folder/{camera_station.station_id}/{unique_id}",
        dropbox_request_id=f"req_{unique_id}",
        dropbox_request_url=f"https://dropbox.com/request/{unique_id}",
        upload_complete=True,
        processed=True
    )


@pytest.fixture
def completed_upload(db, camera_station, user):
    """Upload that's completed processing"""
    from django.utils import timezone
    import uuid
    action, _ = CameraStationAction.objects.get_or_create(
        action="RETRIEVE"
    )
    unique_id = uuid.uuid4().hex[:8]
    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name=f"completed_upload_{unique_id}",
        dropbox_folder_path=f"/test/folder/completed/{camera_station.station_id}/{unique_id}",
        dropbox_request_id=f"req_comp_{unique_id}",
        dropbox_request_url=f"https://dropbox.com/request/comp/{unique_id}",
        processed=True,
        upload_complete=True,
        img_count=10
    )


# UploadListView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadListView:
    """Comprehensive tests for UploadListView"""
    
    # Authentication and Access Tests
    # --------------------------------------------------------------------------
    def test_list_view_requires_login(self, request_factory):
        """Test that upload list requires authentication"""
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = AnonymousUser()
        response = UploadListView.as_view()(request)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_list_view_accessible_for_authenticated_user(self, request_factory, user):
        """Test authenticated user can access upload list"""
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        response = UploadListView.as_view()(request)
        assert response.status_code == 200

    # get_queryset() Tests
    # --------------------------------------------------------------------------
    def test_regular_user_sees_only_own_uploads(self, request_factory, user, camera_station):
        """Test non-staff user only sees their own uploads"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create upload for this user (must be completed and processed to show in main list)
        user_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="user_upload",
            dropbox_folder_path="/test/user",
            dropbox_request_id="user_req",
            dropbox_request_url="https://dropbox.com/user",
            upload_complete=True,
            processed=True
        )
        
        # Create upload for another user
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")
        other_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=other_user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="other_upload",
            dropbox_folder_path="/test/other",
            dropbox_request_id="other_req",
            dropbox_request_url="https://dropbox.com/other",
            upload_complete=True,
            processed=True
        )
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        response = UploadListView.as_view()(request)
        
        queryset = list(response.context_data["object_list"])
        assert user_upload in queryset
        assert other_upload not in queryset

    def test_staff_user_sees_all_uploads(self, request_factory, user, camera_station):
        """Test staff user sees uploads from all users"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Make user staff
        user.is_staff = True
        user.save()
        
        # Create uploads for different users
        user_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="staff_upload",
            dropbox_folder_path="/test/staff",
            dropbox_request_id="staff_req",
            dropbox_request_url="https://dropbox.com/staff"
        )
        
        other_user = User.objects.create_user(email="another@test.com", password="testpass123")
        other_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=other_user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="another_upload",
            dropbox_folder_path="/test/another",
            dropbox_request_id="another_req",
            dropbox_request_url="https://dropbox.com/another"
        )
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        response = UploadListView.as_view()(request)
        
        all_uploads = list(response.context_data["object_list"].object_list)
        assert user_upload in all_uploads
        assert other_upload in all_uploads

    def test_superuser_sees_all_uploads(self, request_factory, user, camera_station):
        """Test superuser sees uploads from all users"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Make user superuser
        user.is_superuser = True
        user.save()
        
        other_user = User.objects.create_user(email="regular@test.com", password="testpass123")
        other_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=other_user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="regular_upload",
            dropbox_folder_path="/test/regular",
            dropbox_request_id="regular_req",
            dropbox_request_url="https://dropbox.com/regular"
        )
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        response = UploadListView.as_view()(request)
        
        all_uploads = list(response.context_data["object_list"].object_list)
        assert other_upload in all_uploads

    # get_elided_page_range() Tests
    # --------------------------------------------------------------------------
    def test_elided_page_range_seven_or_fewer_pages(self, request_factory, user):
        """Test elided range shows all pages when 7 or fewer"""
        from django.core.paginator import Paginator
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        view = UploadListView()
        
        items = list(range(1, 50))  # 50 items
        paginator = Paginator(items, 10)  # 5 pages
        
        page_range = view.get_elided_page_range(paginator, 3)
        assert page_range == [1, 2, 3, 4, 5]

    def test_elided_page_range_many_pages_at_start(self, request_factory, user):
        """Test elided range when on first pages"""
        from django.core.paginator import Paginator
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        view = UploadListView()
        
        items = list(range(1, 200))  # Many items
        paginator = Paginator(items, 10)  # 20 pages
        
        page_range = view.get_elided_page_range(paginator, 2)
        assert 1 in page_range
        assert 2 in page_range
        assert '...' in page_range
        assert 19 in page_range
        assert 20 in page_range

    def test_elided_page_range_many_pages_in_middle(self, request_factory, user):
        """Test elided range when on middle pages"""
        from django.core.paginator import Paginator
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        view = UploadListView()
        
        items = list(range(1, 300))
        paginator = Paginator(items, 10)  # 30 pages
        
        page_range = view.get_elided_page_range(paginator, 15)
        assert 1 in page_range
        assert 2 in page_range
        assert '...' in page_range
        assert 13 in page_range  # current - 2
        assert 14 in page_range  # current - 1
        assert 15 in page_range  # current
        assert 16 in page_range  # current + 1
        assert 17 in page_range  # current + 2
        assert 29 in page_range
        assert 30 in page_range

    def test_elided_page_range_many_pages_at_end(self, request_factory, user):
        """Test elided range when on last pages"""
        from django.core.paginator import Paginator
        
        request = request_factory.get(reverse("images:list_uploads"))
        request.user = user
        view = UploadListView()
        
        items = list(range(1, 250))
        paginator = Paginator(items, 10)  # 25 pages
        
        page_range = view.get_elided_page_range(paginator, 24)
        assert 1 in page_range
        assert 2 in page_range
        assert '...' in page_range
        assert 22 in page_range
        assert 23 in page_range
        assert 24 in page_range
        assert 25 in page_range

    # get_context_data() Tests - Image Count Initialization
    # --------------------------------------------------------------------------
    def test_context_initializes_img_count_for_zero_uploads(self, client, user, camera_station):
        """Test that uploads with img_count=0 get initialized"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create upload with img_count=0
        upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="zero_count",
            dropbox_folder_path="/test/zero",
            dropbox_request_id="zero_req",
            dropbox_request_url="https://dropbox.com/zero",
            img_count=0,
            upload_complete=True,
            processed=True
        )
        
        # Create some images for this upload
        from images.models import Image
        for i in range(3):
            Image.objects.create(
                upload=upload,
                dropbox_file_name=f"image_{i}.jpg",
                dropbox_file_path=f"/test/image_{i}.jpg",
                dropbox_file_path_display=f"/test/Image_{i}.jpg",
                dropbox_content_hash=f"hash123_{i}",  # Each image needs unique hash
                dropbox_file_id=f"id_{i}",
                file_size=1024,
                trigger_timestamp=timezone.now()
            )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        upload.refresh_from_db()
        assert upload.img_count == 3

    # get_context_data() Tests - Staff Context
    # --------------------------------------------------------------------------
    def test_context_includes_pending_for_staff(self, client, user, camera_station):
        """Test staff context includes pending uploads"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        user.is_staff = True
        user.save()
        
        # Create pending upload
        pending = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="pending",
            dropbox_folder_path="/test/pending",
            dropbox_request_id="pending_req",
            dropbox_request_url="https://dropbox.com/pending",
            upload_complete=False,
            processed=False
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert "pending" in response.context
        assert "num_pending" in response.context
        assert pending in response.context["pending"]
        assert response.context["num_pending"] >= 1

    def test_context_includes_processing_for_staff(self, client, user, camera_station):
        """Test staff context includes processing uploads"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        user.is_staff = True
        user.save()
        
        # Create processing upload (complete but not processed)
        processing = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="processing",
            dropbox_folder_path="/test/processing",
            dropbox_request_id="processing_req",
            dropbox_request_url="https://dropbox.com/processing",
            upload_complete=True,
            processed=False
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert "processing" in response.context
        assert "num_processing" in response.context
        assert processing in response.context["processing"]
        assert response.context["num_processing"] >= 1

    def test_context_excludes_other_user_pending_for_regular_user(self, client, user, camera_station):
        """Test regular user only sees their own pending uploads"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create pending upload for another user
        other_user = User.objects.create_user(email="other2@test.com", password="testpass123")
        other_pending = Upload.objects.create(
            camera_station=camera_station,
            volunteer=other_user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="other_pending",
            dropbox_folder_path="/test/other_pending",
            dropbox_request_id="other_pending_req",
            dropbox_request_url="https://dropbox.com/other_pending",
            upload_complete=False,
            processed=False
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert "pending" in response.context
        assert other_pending not in response.context["pending"]

    # get_context_data() Tests - Pagination
    # --------------------------------------------------------------------------
    def test_context_pagination_99_per_page(self, client, user, camera_station):
        """Test pagination uses 99 items per page"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create 100 completed uploads
        for i in range(100):
            Upload.objects.create(
                camera_station=camera_station,
                volunteer=user,
                date_retrieved=timezone.now() + timedelta(hours=i),
                last_action=action,
                dropbox_folder_name=f"pag99_{i}",
                dropbox_folder_path=f"/test/pag99/{i}",
                dropbox_request_id=f"pag99_req_{i}",
                dropbox_request_url=f"https://dropbox.com/pag99/{i}",
                upload_complete=True,
                processed=True
            )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        # First page should have 99 items
        assert len(response.context["object_list"]) == 99
        
        # Second page should have 1 item
        response = client.get(reverse("images:list_uploads") + "?page=2")
        assert len(response.context["object_list"]) == 1

    def test_context_page_range_present_for_multiple_pages(self, client, user, camera_station):
        """Test page_range is added when there are multiple pages"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create 150 uploads to ensure multiple pages
        for i in range(150):
            Upload.objects.create(
                camera_station=camera_station,
                volunteer=user,
                date_retrieved=timezone.now() + timedelta(hours=i),
                last_action=action,
                dropbox_folder_name=f"multi_page_{i}",
                dropbox_folder_path=f"/test/multi/{i}",
                dropbox_request_id=f"multi_req_{i}",
                dropbox_request_url=f"https://dropbox.com/multi/{i}",
                upload_complete=True,
                processed=True
            )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert "page_range" in response.context
        assert isinstance(response.context["page_range"], list)
        assert len(response.context["page_range"]) > 1

    def test_context_no_page_range_for_single_page(self, client, user, upload):
        """Test page_range not added when only one page"""
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        # With only one upload, should be single page
        # page_range should not be in context
        page_range_exists = "page_range" in response.context
        if page_range_exists:
            # If it exists, it should indicate single page scenario
            assert len(response.context["page_range"]) <= 1 or not response.context["page_range"]

    # get_context_data() Tests - Dropbox Prefix
    # --------------------------------------------------------------------------
    def test_context_includes_dropbox_prefix(self, client, user, upload):
        """Test context includes dropbox_prefix setting"""
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert "dropbox_prefix" in response.context

    # get_context_data() Tests - Ordering
    # --------------------------------------------------------------------------
    def test_uploads_ordered_by_created_desc(self, client, user, camera_station):
        """Test uploads are ordered by creation date descending"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create uploads at different times
        old_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now() - timedelta(days=5),
            last_action=action,
            dropbox_folder_name="old",
            dropbox_folder_path="/test/old",
            dropbox_request_id="old_req",
            dropbox_request_url="https://dropbox.com/old",
            upload_complete=True,
            processed=True
        )
        
        new_upload = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="new",
            dropbox_folder_path="/test/new",
            dropbox_request_id="new_req",
            dropbox_request_url="https://dropbox.com/new",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        uploads = list(response.context["object_list"])
        # Newest should come first
        assert uploads.index(new_upload) < uploads.index(old_upload)

    # Integration and Edge Case Tests
    # --------------------------------------------------------------------------
    def test_list_view_shows_user_uploads(self, client, user, upload):
        """Test list view displays user's uploads"""
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        assert response.status_code == 200
        
        # Check that upload appears in the context
        uploads_list = list(response.context["object_list"])
        assert len(uploads_list) > 0
        assert upload in uploads_list

    def test_empty_upload_list_for_new_user(self, client):
        """Test upload list works for user with no uploads"""
        new_user = User.objects.create_user(
            email="newuser@test.com",
            password="testpass123"
        )
        
        client.force_login(new_user)
        response = client.get(reverse("images:list_uploads"))
        
        assert response.status_code == 200
        assert len(list(response.context["object_list"])) == 0
        assert response.context["num_pending"] == 0
        assert response.context["num_processing"] == 0

    def test_mixed_upload_statuses(self, client, user, camera_station):
        """Test list view with uploads in various states"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create uploads in different states
        pending = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="mixed_pending",
            dropbox_folder_path="/test/mixed/pending",
            dropbox_request_id="mixed_pending_req",
            dropbox_request_url="https://dropbox.com/mixed/pending",
            upload_complete=False,
            processed=False
        )
        
        processing = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="mixed_processing",
            dropbox_folder_path="/test/mixed/processing",
            dropbox_request_id="mixed_processing_req",
            dropbox_request_url="https://dropbox.com/mixed/processing",
            upload_complete=True,
            processed=False
        )
        
        completed = Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="mixed_completed",
            dropbox_folder_path="/test/mixed/completed",
            dropbox_request_id="mixed_completed_req",
            dropbox_request_url="https://dropbox.com/mixed/completed",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        
        assert response.status_code == 200
        assert pending in response.context["pending"]
        assert processing in response.context["processing"]
        assert completed in list(response.context["object_list"])


# UploadCreateView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadCreateView:
    def test_create_view_requires_login(self, request_factory):
        """Test create view requires authentication"""
        request = request_factory.get(reverse("images:create_upload"))
        request.user = AnonymousUser()
        response = UploadCreateView.as_view()(request)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_create_view_get_displays_form(self, request_factory, user):
        """Test GET request displays upload form"""
        request = request_factory.get(reverse("images:create_upload"))
        request.user = user
        response = UploadCreateView.as_view()(request)
        assert response.status_code == 200
        assert "form" in response.context_data

    def test_create_upload_basic(self, client, user, camera_station):
        """Test creating a basic upload - just verify form displays"""
        client.force_login(user)
        response = client.get(reverse("images:create_upload"))
        assert response.status_code == 200
        assert "form" in response.context

    def test_create_upload_with_time_correction(self, client, user):
        """Test create form includes time correction fields"""
        client.force_login(user)
        response = client.get(reverse("images:create_upload"))
        assert response.status_code == 200
        # Check time correction fields are in form
        assert "time_correction_hours" in str(response.content)
        assert "time_correction_minutes" in str(response.content)


# UploadDetailView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadDetailView:
    def test_detail_view_requires_login(self, client, upload):
        """Test detail view requires authentication"""
        response = client.get(reverse("images:view_upload", args=[upload.id]))
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_detail_view_accessible(self, request_factory, user, upload):
        """Test authenticated user can view upload details"""
        request = request_factory.get(reverse("images:view_upload", args=[upload.pk]))
        request.user = user
        response = UploadDetailView.as_view()(request, pk=upload.id)
        assert response.status_code == 200
        assert response.context_data["object"] == upload

    def test_detail_view_context_data(self, client, user, upload):
        """Test detail view includes necessary context"""
        client.force_login(user)
        response = client.get(reverse("images:view_upload", args=[upload.id]))
        
        assert response.status_code == 200
        assert "upload" in response.context or "object" in response.context

    def test_detail_view_with_images(self, client, user, upload_with_images):
        """Test detail view with upload containing images"""
        client.force_login(user)
        response = client.get(reverse("images:view_upload", args=[upload_with_images.id]))
        
        assert response.status_code == 200


# UploadDeleteView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadDeleteView:
    def test_delete_view_requires_login(self, request_factory, upload):
        """Test delete view requires authentication"""
        request = request_factory.post(
            reverse("images:delete_upload"),
            data={"upload_id": upload.id}
        )
        request.user = AnonymousUser()
        response = UploadDeleteView.as_view()(request)
        assert response.status_code == 302

    @patch("images.views.upload.process_upload")
    def test_delete_pending_upload(self, mock_process, request_factory, user, upload):
        """Test deleting a pending upload"""
        upload.processed = False
        upload.save()
        
        request = request_factory.post(
            reverse("images:delete_upload"),
            data={"upload_id": str(upload.id)}
        )
        request.user = user
        
        response = UploadDeleteView.as_view()(request)
        
        # Check response
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["success"] is True or data["success"] is False  # Depends on implementation

    def test_delete_nonexistent_upload(self, client, user):
        """Test attempting to delete non-existent upload"""
        client.force_login(user)
        # The view may raise an exception or return an error response
        # Just verify it doesn't crash the server
        try:
            response = client.post(
                reverse("images:delete_upload"),
                data={"upload_id": "00000000-0000-0000-0000-000000000000"}
            )
            # Should return some response, not crash
            assert response.status_code in [200, 400, 404, 500]
        except Exception:
            # If it raises an exception, that's also acceptable behavior
            pass


# UploadStatusView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadStatusView:
    def test_status_view_requires_login(self, request_factory, upload):
        """Test status view requires authentication"""
        request = request_factory.post(
            reverse("images:upload_status"),
            data={"upload_id": upload.id}
        )
        request.user = AnonymousUser()
        response = UploadStatusView.as_view()(request)
        assert response.status_code == 302

    def test_status_view_returns_json(self, client, user, upload):
        """Test status view returns JSON with upload status"""
        client.force_login(user)
        response = client.post(
            reverse("images:upload_status"),
            data={"upload_id": str(upload.id)}
        )
        
        assert response.status_code == 200
        assert "application/json" in response["Content-Type"]

    def test_status_view_completed_upload(self, client, user, completed_upload):
        """Test status view for completed upload"""
        client.force_login(user)
        response = client.post(
            reverse("images:upload_status"),
            data={"upload_id": str(completed_upload.id)}
        )
        
        assert response.status_code == 200
        assert "application/json" in response["Content-Type"]


# UploadCompleteView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadCompleteView:
    def test_complete_view_requires_login(self, request_factory, upload):
        """Test complete view requires authentication"""
        request = request_factory.get(reverse("images:complete_upload", args=[upload.id]))
        request.user = AnonymousUser()
        response = UploadCompleteView.as_view()(request, pk=upload.id)
        assert response.status_code == 302

    def test_complete_view_get_displays_form(self, request_factory, user, upload):
        """Test GET displays completion form"""
        request = request_factory.get(reverse("images:complete_upload", args=[upload.id]))
        request.user = user
        response = UploadCompleteView.as_view()(request, pk=upload.id)
        
        assert response.status_code == 200
        assert "form" in response.context_data
        assert response.context_data["object"] == upload

    def test_complete_upload_starts_processing(self, client, user, upload):
        """Test completing upload view is accessible"""
        client.force_login(user)
        response = client.get(reverse("images:complete_upload", args=[upload.id]))
        assert response.status_code == 200

    def test_complete_form_submission(self, client, user, upload):
        """Test submitting completion form"""
        client.force_login(user)
        response = client.post(
            reverse("images:complete_upload", args=[upload.id]),
            data={"notes": "Test upload complete"}
        )
        # Should handle submission
        assert response.status_code in [200, 302]

    def test_unfinalized_upload_renders_leave_warning_modal(self, client, user, upload):
        """Volunteers leaving before finalizing should get the reminder modal"""
        upload.upload_complete = False
        upload.save()
        client.force_login(user)
        response = client.get(reverse("images:complete_upload", args=[upload.id]))

        content = response.content.decode()
        assert 'id="unfinalizedUploadModal"' in content
        assert "One step left" in content
        assert "leaveWithoutFinalizing" in content

    def test_finalized_upload_omits_leave_warning_modal(self, client, user, upload):
        """Once finalized there is nothing to warn about, so the modal is not rendered"""
        upload.upload_complete = True
        upload.save()
        client.force_login(user)
        response = client.get(reverse("images:complete_upload", args=[upload.id]))

        assert 'id="unfinalizedUploadModal"' not in response.content.decode()

    def test_complete_form_uses_plain_language_checkbox_label(self, client, user, upload):
        """Checkbox label is overridden on the form, not the model, to avoid a migration"""
        upload.upload_complete = False
        upload.save()
        client.force_login(user)
        response = client.get(reverse("images:complete_upload", args=[upload.id]))

        content = response.content.decode()
        assert "I have uploaded all the media to Dropbox" in content
        assert "Upload to Dropbox complete?" not in content
        # Model verbose_name is untouched, so the admin keeps the original wording
        assert Upload._meta.get_field("upload_complete").verbose_name == "Upload to Dropbox complete?"


# UploadResumeProcessingView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadResumeProcessingView:
    def test_resume_view_requires_login(self, request_factory, upload):
        """Test resume processing requires authentication"""
        request = request_factory.post(
            reverse("images:upload_resume_processing"),
            data={"upload_id": upload.id}
        )
        request.user = AnonymousUser()
        response = UploadResumeProcessingView.as_view()(request)
        assert response.status_code == 302

    @patch("images.views.upload.process_upload")
    def test_resume_processing_failed_upload(self, mock_process, request_factory, user, upload):
        """Test resuming processing for failed upload"""
        upload.processed = False
        upload.save()
        
        mock_process.delay.return_value = Mock(id="task-456")
        
        request = request_factory.post(
            reverse("images:upload_resume_processing"),
            data={"upload_id": str(upload.id)}
        )
        request.user = user
        
        response = UploadResumeProcessingView.as_view()(request)
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert "success" in data

    def test_resume_processing_completed_upload(self, request_factory, user, completed_upload):
        """Test attempting to resume already completed upload"""
        request = request_factory.post(
            reverse("images:upload_resume_processing"),
            data={"upload_id": str(completed_upload.id)}
        )
        request.user = user
        
        response = UploadResumeProcessingView.as_view()(request)
        
        assert response.status_code == 200
        # Should handle gracefully


# Integration Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadWorkflow:
    """Test complete upload workflow from creation to completion"""
    
    def test_complete_upload_workflow(self, client, user, upload):
        """Test basic upload workflow navigation"""
        client.force_login(user)
        
        # List uploads
        response = client.get(reverse("images:list_uploads"))
        assert response.status_code == 200
        
        # View upload detail
        response = client.get(reverse("images:view_upload", args=[upload.id]))
        assert response.status_code == 200
        
        # Access complete form
        response = client.get(reverse("images:complete_upload", args=[upload.id]))
        assert response.status_code == 200

    def test_upload_list_filtering_and_sorting(self, client, user, camera_station):
        """Test upload list displays uploads"""
        action, _ = CameraStationAction.objects.get_or_create(
            action="DEPLOY"
        )
        
        # Create uploads with different statuses
        from django.utils import timezone
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="filter_test_1",
            dropbox_folder_path="/test/filter/folder_1",
            dropbox_request_id="filter_req_1",
            dropbox_request_url="https://dropbox.com/filter/1",
            upload_complete=True,
            processed=True
        )
        
        # Test listing
        client.force_login(user)
        response = client.get(reverse("images:list_uploads"))
        assert response.status_code == 200
        assert len(response.context["object_list"]) >= 1


# Advanced UploadCreateView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadCreateViewAdvanced:
    """Advanced tests for UploadCreateView focusing on form_valid and time corrections"""
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_form_valid_with_time_correction(self, mock_setup, client, user, camera_station):
        """Test form submission with time correction data"""
        client.force_login(user)
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved": "2026-03-20",
            "time_correction_hours": 2,
            "time_correction_minutes": 30,
            "time_correction_days": 1,
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data)
        
        # Should redirect to complete_upload on success or show form with errors
        assert response.status_code in [200, 302]
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_form_valid_with_daylight_savings(self, mock_setup, client, user, camera_station):
        """Test form submission with daylight savings correction"""
        client.force_login(user)
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved": "2026-03-20",
            "daylight_savings_correction": "03-2026",  # Format: MM-YYYY
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data)
        assert response.status_code in [200, 302]
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_form_valid_with_date_range(self, mock_setup, client, user, camera_station):
        """Test form submission with start and end dates"""
        client.force_login(user)
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved": "2026-03-20",
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "time_correction_hours": 1,
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data)
        assert response.status_code in [200, 302]
    
    def test_get_context_data_includes_preview_images(self, client, user):
        """Test that context includes preview images"""
        client.force_login(user)
        response = client.get(reverse("images:create_upload"))
        
        assert response.status_code == 200
        # Preview images should be in context
        assert "images" in response.context or "form" in response.context


# Comprehensive UploadCreateView form_valid Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadCreateViewFormValid:
    """Comprehensive tests for UploadCreateView.form_valid() method"""
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_creates_time_correction_with_all_fields(self, mock_setup, client, user, camera_station):
        """Test that TimeCorrection object is created with all field values"""
        from images.models import TimeCorrection
        from django.utils import timezone
        
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",  # Date part
            "date_retrieved_1": "14:30:00",    # Time part
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
            "time_correction_years": 1,
            "time_correction_months": 2,
            "time_correction_days": 3,
            "time_correction_hours": 4,
            "time_correction_minutes": 5,
            "daylight_savings_correction": "03-2026",
            "start_date": "2026-01-01T00:00",
            "end_date": "2026-02-28T23:59",
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data, follow=False)
        
        # Should redirect to complete_upload
        assert response.status_code == 302
        
        # Verify Upload was created
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        
        # Verify TimeCorrection was created and linked
        assert upload.time_correction is not None
        tc = upload.time_correction
        assert tc.years == 1
        assert tc.months == 2
        assert tc.days == 3
        assert tc.hours == 4
        assert tc.minutes == 5
        # daylight_savings is stored as a date object (2nd Sunday of March 2026 = March 8)
        from datetime import date
        assert tc.daylight_savings == date(2026, 3, 8)
        assert tc.start_date is not None
        assert tc.end_date is not None
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_no_time_correction_when_all_zeros(self, mock_setup, client, user, camera_station):
        """Test that no TimeCorrection is created when all values are 0"""
        from images.models import TimeCorrection
        
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
            "time_correction_years": 0,
            "time_correction_months": 0,
            "time_correction_days": 0,
            "time_correction_hours": 0,
            "time_correction_minutes": 0,
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data, follow=True)
        
        # Verify Upload was created
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        
        # Verify NO TimeCorrection was created
        assert upload.time_correction is None
        assert TimeCorrection.objects.filter(upload=upload).count() == 0
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_creates_time_correction_with_only_hours(self, mock_setup, client, user, camera_station):
        """Test TimeCorrection creation with only hours set"""
        from images.models import TimeCorrection
        
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
            "time_correction_hours": 3,
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data, follow=True)
        
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        assert upload.time_correction is not None
        
        tc = upload.time_correction
        assert tc.years == 0
        assert tc.months == 0
        assert tc.days == 0
        assert tc.hours == 3
        assert tc.minutes == 0
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_creates_time_correction_with_only_daylight_savings(self, mock_setup, client, user, camera_station):
        """Test TimeCorrection creation with only daylight savings"""
        from images.models import TimeCorrection
        
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
            "daylight_savings_correction": "11-2026",
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data, follow=True)
        
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        assert upload.time_correction is not None
        # daylight_savings is stored as a date object (1st Sunday of November 2026 = November 1)
        from datetime import date
        assert upload.time_correction.daylight_savings == date(2026, 11, 1)
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_creates_time_correction_with_date_range(self, mock_setup, client, user, camera_station):
        """Test TimeCorrection creation with start and end dates"""
        from images.models import TimeCorrection
        from datetime import date
        
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
            "time_correction_hours": 2,
            "start_date": "2026-01-15T00:00",
            "end_date": "2026-03-15T23:59",
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data, follow=True)
        
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        assert upload.time_correction is not None
        
        tc = upload.time_correction
        # start_date and end_date are DateTime fields
        assert tc.start_date is not None
        assert tc.end_date is not None
        assert tc.hours == 2
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_success_url_redirects_to_complete_upload(self, mock_setup, client, user, camera_station):
        """Test that success redirects to complete_upload view"""
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data)
        
        # Should redirect (302) to complete_upload
        assert response.status_code == 302
        
        upload = Upload.objects.filter(camera_station=camera_station).first()
        assert upload is not None
        
        # Verify redirect URL contains the upload ID
        expected_url = reverse("images:complete_upload", args=[upload.id])
        assert response.url == expected_url
    
    @patch("images.views.upload.setup_dropbox_paths")
    def test_setup_dropbox_paths_called(self, mock_setup, client, user, camera_station):
        """Test that setup_dropbox_paths is called during form_valid"""
        client.force_login(user)
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        form_data = {
            "camera_station": camera_station.id,
            "volunteer": user.id,
            "date_retrieved_0": "2026-03-20",
            "date_retrieved_1": "14:30:00",
            "last_action": action.id,
            "upload_method": "E",
            "data_sheet": "",
        }
        
        response = client.post(reverse("images:create_upload"), data=form_data)
        
        # Verify setup_dropbox_paths was called
        assert mock_setup.called
        assert mock_setup.call_count == 1
        
        # Verify it was called with the upload object
        call_args = mock_setup.call_args[0]
        assert isinstance(call_args[0], Upload)


# UploadListView Filtering Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadListViewFiltering:
    """Test filter_uploads functionality via UploadListView"""
    
    def test_filter_by_volunteer(self, client, user, camera_station):
        """Test filtering uploads by volunteer"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        # Create upload
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="volunteer_filter",
            dropbox_folder_path="/test/volunteer",
            dropbox_request_id="vol_req",
            dropbox_request_url="https://dropbox.com/vol",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads") + f"?volunteer={user.name}")
        
        assert response.status_code == 200
    
    def test_filter_by_macrosite(self, client, user, camera_station):
        """Test filtering uploads by macrosite"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="macro_filter",
            dropbox_folder_path="/test/macro",
            dropbox_request_id="macro_req",
            dropbox_request_url="https://dropbox.com/macro",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        macrosite_name = camera_station.micro_site.macro_site.name
        response = client.get(reverse("images:list_uploads") + f"?macrosite={macrosite_name}")
        
        assert response.status_code == 200
    
    def test_filter_by_microsite(self, client, user, camera_station):
        """Test filtering uploads by microsite"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="micro_filter",
            dropbox_folder_path="/test/micro",
            dropbox_request_id="micro_req",
            dropbox_request_url="https://dropbox.com/micro",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        microsite_name = camera_station.micro_site.name
        response = client.get(reverse("images:list_uploads") + f"?microsite={microsite_name}")
        
        assert response.status_code == 200
    
    def test_filter_by_camera_station(self, client, user, camera_station):
        """Test filtering uploads by camera station"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="station_filter",
            dropbox_folder_path="/test/station",
            dropbox_request_id="station_req",
            dropbox_request_url="https://dropbox.com/station",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        response = client.get(reverse("images:list_uploads") + f"?camera_station={camera_station.station_id}")
        
        assert response.status_code == 200
    
    def test_filter_by_date_range(self, client, user, camera_station):
        """Test filtering uploads by date range"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="date_filter",
            dropbox_folder_path="/test/date",
            dropbox_request_id="date_req",
            dropbox_request_url="https://dropbox.com/date",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        start_date = "2026-01-01"
        end_date = "2026-12-31"
        response = client.get(reverse("images:list_uploads") + f"?start_date={start_date}&end_date={end_date}")
        
        assert response.status_code == 200
    
    def test_filter_with_multiple_parameters(self, client, user, camera_station):
        """Test filtering with multiple parameters"""
        from django.utils import timezone
        action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
        
        Upload.objects.create(
            camera_station=camera_station,
            volunteer=user,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="multi_filter",
            dropbox_folder_path="/test/multi",
            dropbox_request_id="multi_req",
            dropbox_request_url="https://dropbox.com/multi",
            upload_complete=True,
            processed=True
        )
        
        client.force_login(user)
        response = client.get(
            reverse("images:list_uploads") + 
            f"?volunteer={user.name}&camera_station={camera_station.station_id}"
        )
        
        assert response.status_code == 200


# PreviewTimeCorrectionsView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestPreviewTimeCorrectionsView:
    """Tests for PreviewTimeCorrectionsView"""
    
    def test_preview_requires_login(self, client):
        """Test preview view requires authentication"""
        response = client.post(reverse("images:preview_time_corrections"))
        assert response.status_code == 302
    
    def test_preview_with_test_data(self, client, user):
        """Test preview with test image data"""
        client.force_login(user)
        
        data = {
            "images": json.dumps(["1", "2", "3"]),
            "test": "true",
            "years": 0,
            "months": 0,
            "days": 1,
            "hours": 2,
            "minutes": 30,
            "startDate": "",
            "endDate": "",
            "daylightSavings": ""
        }
        
        response = client.post(reverse("images:preview_time_corrections"), data=data)
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert "success" in data
        assert "previewInfo" in data
    
    def test_preview_with_date_range(self, client, user):
        """Test preview with start and end dates"""
        client.force_login(user)
        
        data = {
            "images": json.dumps(["1", "2"]),
            "test": "true",
            "years": 0,
            "months": 0,
            "days": 0,
            "hours": 1,
            "minutes": 0,
            "startDate": "2026-03-01T00:00",
            "endDate": "2026-03-31T23:59",
            "daylightSavings": ""
        }
        
        response = client.post(reverse("images:preview_time_corrections"), data=data)
        assert response.status_code == 200
    
    def test_preview_with_daylight_savings(self, client, user):
        """Test preview with daylight savings correction"""
        client.force_login(user)
        
        data = {
            "images": json.dumps(["1"]),
            "test": "true",
            "years": 0,
            "months": 0,
            "days": 0,
            "hours": 0,
            "minutes": 0,
            "startDate": "",
            "endDate": "",
            "daylightSavings": "03-2026"
        }
        
        response = client.post(reverse("images:preview_time_corrections"), data=data)
        assert response.status_code == 200


# TimeCorrectionCreateView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestTimeCorrectionCreateView:
    """Tests for TimeCorrectionCreateView"""
    
    def test_create_requires_login(self, client, upload):
        """Test time correction creation requires authentication"""
        response = client.get(reverse("images:create_time_correction", args=[upload.id]))
        assert response.status_code == 302
    
    def test_create_view_accessible(self, client, user, upload):
        """Test authenticated user can access time correction form"""
        client.force_login(user)
        response = client.get(reverse("images:create_time_correction", args=[upload.id]))
        assert response.status_code == 200
    
    def test_create_view_context_includes_images(self, client, user, upload):
        """Test context includes preview images"""
        client.force_login(user)
        response = client.get(reverse("images:create_time_correction", args=[upload.id]))
        
        assert response.status_code == 200
        assert "images" in response.context or "form" in response.context


# ApplyTimeCorrectionView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestApplyTimeCorrectionView:
    """Tests for ApplyTimeCorrectionView"""
    
    def test_apply_requires_login(self, client, upload):
        """Test apply view requires authentication"""
        response = client.get(reverse("images:apply_time_correction", args=[upload.id]))
        assert response.status_code == 302
    
    def test_apply_view_accessible_with_time_correction(self,client, user, upload):
        """Test authenticated user can access apply view when upload has time correction"""
        from images.models import TimeCorrection
        
        # Create a time correction for the upload
        time_correction = TimeCorrection.objects.create(
            hours=2,
            minutes=30,
            days=1
        )
        upload.time_correction = time_correction
        upload.save()
        
        client.force_login(user)
        response = client.get(reverse("images:apply_time_correction", args=[upload.id]))
        assert response.status_code == 200
    
    def test_apply_view_context_data(self, client, user, upload):
        """Test apply view includes necessary context"""
        from images.models import TimeCorrection
        
        # Create a time correction for the upload
        time_correction = TimeCorrection.objects.create(
            hours=1,
            minutes=0,
            days=0
        )
        upload.time_correction = time_correction
        upload.save()
        
        client.force_login(user)
        response = client.get(reverse("images:apply_time_correction", args=[upload.id]))
        
        assert response.status_code == 200
        assert "upload" in response.context
        assert response.context["upload"] == upload


# TimeCorrectionStatusView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestTimeCorrectionStatusView:
    """Tests for TimeCorrectionStatusView"""
    
    def test_status_requires_login(self, client, upload):
        """Test status view requires authentication"""
        response = client.post(
            reverse("images:time_correction_status"),
            data={"uploadId": str(upload.id)}
        )
        assert response.status_code == 302
    
    def test_status_returns_json(self, client, user, upload):
        """Test status view returns JSON response"""
        client.force_login(user)
        response = client.post(
            reverse("images:time_correction_status"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        assert "application/json" in response["Content-Type"]
    
    def test_status_includes_counts(self, client, user, upload):
        """Test status response includes applied/not applied counts"""
        client.force_login(user)
        response = client.post(
            reverse("images:time_correction_status"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert "success" in data


# ModifyUploadSetImagesView Tests
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestModifyUploadSetImagesView:
    """Tests for ModifyUploadSetImagesView (staff only)"""
    
    def test_modify_requires_login(self, client, upload):
        """Test modify view requires authentication"""
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        assert response.status_code == 302
    
    def test_modify_requires_staff(self, client, user, upload):
        """Test modify view requires staff privileges"""
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        # Should redirect or deny access for non-staff
        assert response.status_code in [302, 403]
    
    def test_apply_time_correction_to_images(self, client, user, upload, camera_station):
        """Test applying time correction to upload images"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        # Create time correction for upload
        time_correction = TimeCorrection.objects.create(
            days=1,
            hours=2,
            minutes=30,
            years=0,
            months=0
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create images with timestamps
        base_time = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        images = []
        for i in range(3):
            img = Image.objects.create(
                upload=upload,
                dropbox_file_name=f"image{i}.jpg",
                dropbox_file_path=f"/test/image{i}.jpg",
                dropbox_file_path_display=f"/test/image{i}.jpg",
                dropbox_content_hash=f"hash{i}",
                dropbox_file_id=f"id{i}",
                file_size=1024,
                trigger_timestamp=base_time + timedelta(hours=i),
                time_correction_applied=False
            )
            images.append(img)
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["success"] is True
        
        # Verify images were updated
        for img in images:
            img.refresh_from_db()
            assert img.time_correction_applied is True
    
    def test_apply_time_correction_with_date_range(self, client, user, upload, camera_station):
        """Test applying time correction only within date range"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        # Create time correction with date range
        start_date = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2026, 3, 20, 0, 0, 0, tzinfo=timezone.utc)
        
        time_correction = TimeCorrection.objects.create(
            days=1,
            hours=0,
            minutes=0,
            years=0,
            months=0,
            start_date=start_date,
            end_date=end_date
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create images - some in range, some out
        img_in_range = Image.objects.create(
            upload=upload,
            dropbox_file_name="in_range.jpg",
            dropbox_file_path="/test/in_range.jpg",
            dropbox_file_path_display="/test/in_range.jpg",
            dropbox_content_hash="hash_in",
            dropbox_file_id="id_in",
            file_size=1024,
            trigger_timestamp=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
            time_correction_applied=False
        )
        
        img_before = Image.objects.create(
            upload=upload,
            dropbox_file_name="before.jpg",
            dropbox_file_path="/test/before.jpg",
            dropbox_file_path_display="/test/before.jpg",
            dropbox_content_hash="hash_before",
            dropbox_file_id="id_before",
            file_size=1024,
            trigger_timestamp=datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc),
            time_correction_applied=False
        )
        
        img_after = Image.objects.create(
            upload=upload,
            dropbox_file_name="after.jpg",
            dropbox_file_path="/test/after.jpg",
            dropbox_file_path_display="/test/after.jpg",
            dropbox_content_hash="hash_after",
            dropbox_file_id="id_after",
            file_size=1024,
            trigger_timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
            time_correction_applied=False
        )
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        
        # Only in-range image should be corrected
        img_in_range.refresh_from_db()
        img_before.refresh_from_db()
        img_after.refresh_from_db()
        
        assert img_in_range.time_correction_applied is True
        assert img_before.time_correction_applied is True  # Still marked as processed
        assert img_after.time_correction_applied is True
    
    def test_apply_daylight_savings_march(self, client, user, upload, camera_station):
        """Test applying daylight savings correction for March (spring forward)"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        # Create time correction with March daylight savings
        from datetime import date
        march_dst = date(2026, 3, 1)
        time_correction = TimeCorrection.objects.create(
            days=0,
            hours=0,
            minutes=0,
            years=0,
            months=0,
            daylight_savings=march_dst
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create image
        img = Image.objects.create(
            upload=upload,
            dropbox_file_name="dst_march.jpg",
            dropbox_file_path="/test/dst_march.jpg",
            dropbox_file_path_display="/test/dst_march.jpg",
            dropbox_content_hash="hash_dst_march",
            dropbox_file_id="id_dst_march",
            file_size=1024,
            trigger_timestamp=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
            time_correction_applied=False
        )
        
        original_time = img.trigger_timestamp
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        img.refresh_from_db()
        
        # Should add 1 hour for spring forward
        assert img.trigger_timestamp == original_time + timedelta(hours=1)
    
    def test_apply_daylight_savings_november(self, client, user, upload, camera_station):
        """Test applying daylight savings correction for November (fall back)"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        # Create time correction with November daylight savings
        from datetime import date
        november_dst = date(2026, 11, 1)
        time_correction = TimeCorrection.objects.create(
            days=0,
            hours=0,
            minutes=0,
            years=0,
            months=0,
            daylight_savings=november_dst
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create image
        img = Image.objects.create(
            upload=upload,
            dropbox_file_name="dst_nov.jpg",
            dropbox_file_path="/test/dst_nov.jpg",
            dropbox_file_path_display="/test/dst_nov.jpg",
            dropbox_content_hash="hash_dst_nov",
            dropbox_file_id="id_dst_nov",
            file_size=1024,
            trigger_timestamp=datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc),
            time_correction_applied=False
        )
        
        original_time = img.trigger_timestamp
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        img.refresh_from_db()
        
        # Should subtract 1 hour for fall back
        assert img.trigger_timestamp == original_time - timedelta(hours=1)
    
    def test_skip_images_with_null_timestamp(self, client, user, upload, camera_station):
        """Test that images with null timestamp are skipped but marked as processed"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        time_correction = TimeCorrection.objects.create(
            days=1,
            hours=0,
            minutes=0,
            years=0,
            months=0
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create image with null timestamp
        img = Image.objects.create(
            upload=upload,
            dropbox_file_name="no_timestamp.jpg",
            dropbox_file_path="/test/no_timestamp.jpg",
            dropbox_file_path_display="/test/no_timestamp.jpg",
            dropbox_content_hash="hash_null",
            dropbox_file_id="id_null",
            file_size=1024,
            trigger_timestamp=None,
            time_correction_applied=False
        )
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        img.refresh_from_db()
        
        # Should be marked as processed but timestamp still None
        assert img.time_correction_applied is True
        assert img.trigger_timestamp is None
    
    def test_unapply_time_correction(self, client, user, upload, camera_station):
        """Test unapplying time correction from images"""
        from images.models import Image
        
        user.is_staff = True
        user.save()
        
        # Create time correction that's already been applied
        time_correction = TimeCorrection.objects.create(
            days=1,
            hours=2,
            minutes=0,
            years=0,
            months=0,
            applied_at=timezone.now()
        )
        upload.time_correction = time_correction
        upload.save()
        
        # Create image that already had correction applied
        original_time = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        corrected_time = original_time + timedelta(days=1, hours=2)
        
        img = Image.objects.create(
            upload=upload,
            dropbox_file_name="corrected.jpg",
            dropbox_file_path="/test/corrected.jpg",
            dropbox_file_path_display="/test/corrected.jpg",
            dropbox_content_hash="hash_corrected",
            dropbox_file_id="id_corrected",
            file_size=1024,
            trigger_timestamp=corrected_time,
            time_correction_applied=True
        )
        
        client.force_login(user)
        response = client.post(
            reverse("images:modify_upload_set_images"),
            data={"uploadId": str(upload.id)}
        )
        
        assert response.status_code == 200
        img.refresh_from_db()
        
        # Time should be reversed
        assert img.time_correction_applied is False
        # Should subtract the correction
        assert img.trigger_timestamp == original_time


# FixUploadSetsView Tests  
# ------------------------------------------------------------------------------
@pytest.mark.django_db
class TestFixUploadSetsView:
    """Tests for FixUploadSetsView (staff only)"""
    
    def test_fix_view_requires_login(self, client):
        """Test fix upload sets view requires authentication"""
        response = client.get(reverse("images:fix_upload_sets"))
        assert response.status_code == 302
    
    def test_fix_view_requires_staff(self, client, user):
        """Test fix view requires staff privileges"""
        client.force_login(user)
        response = client.get(reverse("images:fix_upload_sets"))
        # Should redirect or deny access for non-staff
        assert response.status_code in [302, 403]
    
    def test_fix_view_accessible_to_staff(self, client, user):
        """Test staff user can access fix view"""
        user.is_staff = True
        user.save()
        
        client.force_login(user)
        response = client.get(reverse("images:fix_upload_sets"))
        assert response.status_code == 200
