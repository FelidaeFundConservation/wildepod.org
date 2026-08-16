"""
Tests for images search_images view.
"""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from images.models import BoundingBox, CameraStationAction, Image, Upload
from images.views.search_images import SearchImagesForm, SearchImagesView
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def staff_user(db):
    """Create a staff user for testing."""
    user = User.objects.create_user(
        email="staffuser@example.com",
        password="testpass123",
        is_staff=True,
    )
    return user


@pytest.fixture
def client_logged_in(staff_user):
    """Create a logged-in client."""
    client = Client()
    client.force_login(staff_user)
    return client


@pytest.fixture
def macro_site(db):
    """Create a MacroSite for testing."""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro_site = MacroSite.objects.create(
        name="Test Macro Site",
        county=county,
    )
    return macro_site


@pytest.fixture
def camera_station(db, macro_site):
    """Create a CameraStation for testing."""
    from django.utils import timezone

    micro_site = MicroSite.objects.create(
        name="Test Micro Site",
        macro_site=macro_site,
    )
    camera_station = CameraStation.objects.create(
        station_id="CAM001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        date_deployed=timezone.now().date(),
    )
    return camera_station


@pytest.fixture
def upload(db, camera_station, staff_user):
    """Create an upload for testing."""
    from django.utils import timezone

    action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")
    upload = Upload.objects.create(
        camera_station=camera_station,
        volunteer=staff_user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="test_folder",
        dropbox_folder_path="/test/folder",
        upload_method="E",
    )
    return upload


@pytest.mark.django_db
class TestSearchImagesForm:
    """Test SearchImagesForm."""

    def test_form_has_required_fields(self):
        """Test that the form has all expected fields."""
        form = SearchImagesForm()

        assert "volunteers" in form.fields
        assert "macrosites" in form.fields
        assert "camera_stations" in form.fields
        assert "species" in form.fields
        assert "species_ai" in form.fields
        assert "search_type" in form.fields
        assert "date" in form.fields
        assert "start_date" in form.fields
        assert "end_date" in form.fields
        assert "hour" in form.fields
        assert "staff_review_needed" in form.fields
        assert "image_reported" in form.fields
        assert "social_media_worthy" in form.fields
        assert "time_filter_type" in form.fields
        assert "annotation_type" in form.fields

    def test_form_fields_are_optional(self):
        """Test that most form fields are optional except required ones."""
        form = SearchImagesForm(
            data={
                "search_type": "OR",
                "time_filter_type": "TT",
                "annotation_type": "SP",
                "hour": 0,
            }
        )

        # Form should be valid with just required fields
        assert form.is_valid()

    def test_search_type_choices(self):
        """Test that search_type has correct choices."""
        form = SearchImagesForm()

        search_type_field = form.fields["search_type"]
        choices = [choice[0] for choice in search_type_field.choices]

        assert "OR" in choices
        assert "AND" in choices


@pytest.mark.django_db
class TestSearchImagesView:
    """Test SearchImagesView."""

    def test_get_requires_login(self, client):
        """Test that GET requires login."""
        url = reverse("images:search_images")
        response = client.get(url)

        # Should redirect to login
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_get_requires_staff(self, db):
        """Test that GET requires staff privileges."""
        # Create non-staff user
        user = User.objects.create_user(
            email="regular@example.com",
            password="testpass123",
            is_staff=False,
        )
        client = Client()
        client.force_login(user)

        url = reverse("images:search_images")
        response = client.get(url, follow=False)

        # Should be forbidden - StaffuserRequiredMixin redirects or returns 403
        # Depending on Django/braces version, could be redirect or 403
        assert response.status_code in [302, 403], f"Expected 302 or 403, got {response.status_code}"

    def test_get_with_staff_user(self, client_logged_in):
        """Test GET with staff user returns form."""
        url = reverse("images:search_images")
        response = client_logged_in.get(url)

        assert response.status_code == 200
        assert "form" in response.context
        assert isinstance(response.context["form"], SearchImagesForm)

    def test_post_with_macro_site_filter(self, client_logged_in, upload, macro_site):
        """Test POST with macrosite filter."""
        from django.utils import timezone

        # Create an image in the upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/thumb.jpg",
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([macro_site.id]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["dropbox_file_name"] == "test.jpg"

    def test_post_with_camera_station_filter(self, client_logged_in, upload, camera_station):
        """Test POST with camera station filter."""
        from django.utils import timezone

        # Create an image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="camera_test.jpg",
            dropbox_file_path="/test/camera_test.jpg",
            dropbox_file_path_display="/test/camera_test.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="file_id_2",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/camera_thumb.jpg",
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([camera_station.id]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1

    def test_post_with_date_filter_trigger_timestamp(self, client_logged_in, upload):
        """Test POST with date filter on trigger timestamp."""
        from django.utils import timezone

        today = timezone.now().date()

        # Create image with today's timestamp
        Image.objects.create(
            upload=upload,
            dropbox_file_name="today.jpg",
            dropbox_file_path="/test/today.jpg",
            dropbox_file_path_display="/test/today.jpg",
            dropbox_content_hash="hash_today",
            dropbox_file_id="file_id_today",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/today_thumb.jpg",
        )

        # Create image with yesterday's timestamp
        yesterday = timezone.now() - timedelta(days=1)
        Image.objects.create(
            upload=upload,
            dropbox_file_name="yesterday.jpg",
            dropbox_file_path="/test/yesterday.jpg",
            dropbox_file_path_display="/test/yesterday.jpg",
            dropbox_content_hash="hash_yesterday",
            dropbox_file_id="file_id_yesterday",
            file_size=1024,
            trigger_timestamp=yesterday,
            thumbnail_gcloud_path="test/yesterday_thumb.jpg",
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
                "date": str(today),
                "time_filter_type": "TT",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["dropbox_file_name"] == "today.jpg"

    def test_post_with_date_range_filter(self, client_logged_in, upload):
        """Test POST with date range filter."""
        from django.utils import timezone

        today = timezone.now().date()
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=1)

        # Create image within range
        Image.objects.create(
            upload=upload,
            dropbox_file_name="in_range.jpg",
            dropbox_file_path="/test/in_range.jpg",
            dropbox_file_path_display="/test/in_range.jpg",
            dropbox_content_hash="hash_range",
            dropbox_file_id="file_id_range",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/range_thumb.jpg",
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
                "start_date": str(start_date),
                "end_date": str(end_date),
                "time_filter_type": "TT",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1

    def test_post_with_staff_review_needed_filter(self, client_logged_in, upload):
        """Test POST with staff_review_needed filter."""
        from django.utils import timezone

        # Create image that needs review
        Image.objects.create(
            upload=upload,
            dropbox_file_name="needs_review.jpg",
            dropbox_file_path="/test/needs_review.jpg",
            dropbox_file_path_display="/test/needs_review.jpg",
            dropbox_content_hash="hash_review",
            dropbox_file_id="file_id_review",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/review_thumb.jpg",
            staff_review_needed=True,
        )

        # Create image that doesn't need review
        Image.objects.create(
            upload=upload,
            dropbox_file_name="no_review.jpg",
            dropbox_file_path="/test/no_review.jpg",
            dropbox_file_path_display="/test/no_review.jpg",
            dropbox_content_hash="hash_no_review",
            dropbox_file_id="file_id_no_review",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/no_review_thumb.jpg",
            staff_review_needed=False,
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
                "staff_review_needed": json.dumps(True),
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["dropbox_file_name"] == "needs_review.jpg"

    def test_post_with_image_reported_filter(self, client_logged_in, upload):
        """Test POST with image_reported filter."""
        from django.utils import timezone

        # Create reported image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="reported.jpg",
            dropbox_file_path="/test/reported.jpg",
            dropbox_file_path_display="/test/reported.jpg",
            dropbox_content_hash="hash_reported",
            dropbox_file_id="file_id_reported",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/reported_thumb.jpg",
            image_reported=True,
        )

        # Create non-reported image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="not_reported.jpg",
            dropbox_file_path="/test/not_reported.jpg",
            dropbox_file_path_display="/test/not_reported.jpg",
            dropbox_content_hash="hash_not_reported",
            dropbox_file_id="file_id_not_reported",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/not_reported_thumb.jpg",
            image_reported=False,
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
                "image_reported": json.dumps(True),
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["dropbox_file_name"] == "reported.jpg"

    def test_post_with_social_media_worthy_filter(self, client_logged_in, upload):
        """Test POST with social_media_worthy filter."""
        from django.utils import timezone

        # Create social media worthy image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="social_media.jpg",
            dropbox_file_path="/test/social_media.jpg",
            dropbox_file_path_display="/test/social_media.jpg",
            dropbox_content_hash="hash_social",
            dropbox_file_id="file_id_social",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/social_thumb.jpg",
            social_media_worthy=5,
        )

        # Create non-worthy image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="not_social.jpg",
            dropbox_file_path="/test/not_social.jpg",
            dropbox_file_path_display="/test/not_social.jpg",
            dropbox_content_hash="hash_not_social",
            dropbox_file_id="file_id_not_social",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/not_social_thumb.jpg",
            social_media_worthy=0,
        )

        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "volunteers": json.dumps([]),
                "search_type": json.dumps("OR"),
                "social_media_worthy": "true",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["dropbox_file_name"] == "social_media.jpg"

    def test_post_with_no_results(self, client_logged_in):
        """Test POST with filters that match no images."""
        url = reverse("images:search_images")
        response = client_logged_in.post(
            url,
            {
                "macrosites": json.dumps([99999]),  # Non-existent ID
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
            },
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "results" in data
        assert len(data["results"]) == 0
