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
from images.models import (
    Annotator,
    BoundingBox,
    CameraStationAction,
    Image,
    StaffReviewFlagReason,
    StaffReviewFlagSource,
    Upload,
)
from images.views.search_images import (
    REVIEW_SESSION_GAP,
    SearchImagesForm,
    SearchImagesView,
    flagged_by_display,
    review_session_anchor,
)
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


def make_search_image(upload, file_name, **fields):
    """An image with only the columns the search view needs, plus whatever is under test."""
    from django.utils import timezone

    stem = file_name.removesuffix(".jpg")

    return Image.objects.create(
        upload=upload,
        dropbox_file_name=file_name,
        dropbox_file_path=f"/test/{file_name}",
        dropbox_file_path_display=f"/test/{file_name}",
        dropbox_content_hash=f"hash_{stem}",
        dropbox_file_id=f"file_id_{stem}",
        file_size=1024,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path=f"test/{stem}_thumb.jpg",
        **fields,
    )


def post_search(client, **filters):
    """A search with the multi-selects empty, so only the named filters are under test."""
    return client.post(
        reverse("images:search_images"),
        {
            "macrosites": json.dumps([]),
            "camera_stations": json.dumps([]),
            "volunteers": json.dumps([]),
            "species": json.dumps([]),
            "species_ai": json.dumps([]),
            "search_type": json.dumps("OR"),
            **{name: json.dumps(value) for name, value in filters.items()},
        },
    )


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

    def _search_range(self, client, upload, start, end):
        from django.utils import timezone

        Image.objects.get_or_create(
            upload=upload,
            dropbox_file_name="on_the_end_day.jpg",
            defaults=dict(
                dropbox_file_path="/test/on_the_end_day.jpg",
                dropbox_file_path_display="/test/on_the_end_day.jpg",
                dropbox_content_hash="hash_end_day",
                dropbox_file_id="file_id_end_day",
                file_size=1024,
                # Late in the day, so an end bound that only reaches midnight would miss it
                trigger_timestamp=timezone.now().replace(hour=23, minute=30),
                thumbnail_gcloud_path="test/end_day_thumb.jpg",
            ),
        )

        response = client.post(
            reverse("images:search_images"),
            {
                "macrosites": json.dumps([]),
                "camera_stations": json.dumps([]),
                "volunteers": json.dumps([]),
                "species": json.dumps([]),
                "species_ai": json.dumps([]),
                "search_type": json.dumps("OR"),
                "time_filter_type": "TT",
                "start_date": str(start),
                "end_date": str(end),
            },
        )
        assert response.status_code == 200
        return json.loads(response.content)["results"]

    def test_date_range_includes_the_end_day(self, client_logged_in, upload):
        """The field is labelled "End Of Date Range", so it must cover the whole of that day.
        An exclusive bound silently trimmed the last day off every search."""
        from django.utils import timezone

        today = timezone.now().date()

        results = self._search_range(client_logged_in, upload, today - timedelta(days=7), today)

        assert any(r["dropbox_file_name"] == "on_the_end_day.jpg" for r in results)

    def test_a_single_day_range_finds_that_day(self, client_logged_in, upload):
        """Start and end on the same day is the natural way to ask for one day's images, and
        with an exclusive end bound it could only ever return nothing."""
        from django.utils import timezone

        today = timezone.now().date()

        results = self._search_range(client_logged_in, upload, today, today)

        assert any(r["dropbox_file_name"] == "on_the_end_day.jpg" for r in results)

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

    def test_reviewed_images_are_not_a_search_checkbox(self, client_logged_in, upload):
        """Deliberately absent from the form. Those boxes OR together, so a stray tick widens
        the search to every image review has ever closed, with a bigger number as the only
        sign. Resolved images are reached through the Reviewed button in the Filter row.
        """
        from django.utils import timezone

        make_search_image(upload, "closed.jpg", staff_reviewed_at=timezone.now())
        make_search_image(upload, "open.jpg", staff_review_needed=True)

        assert "staff_reviewed" not in SearchImagesForm().fields

        # An unrecognised key is ignored rather than widening the query behind the filter row
        response = post_search(client_logged_in, staff_review_needed=True, staff_reviewed=True)

        names = {row["dropbox_file_name"] for row in json.loads(response.content)["results"]}
        assert names == {"open.jpg"}

    def test_results_carry_what_the_reviewed_filter_reads(self, client_logged_in, upload):
        """The Reviewed button and the row's "Reviewed" chip both live off staff_reviewed_at,
        and it reaches them only by being selected here. Without it the button can never
        appear and a resolved row is one with an empty Flags column.
        """
        from django.utils import timezone

        make_search_image(upload, "closed.jpg", staff_reviewed_at=timezone.now())
        make_search_image(upload, "untouched.jpg")

        results = json.loads(post_search(client_logged_in).content)["results"]
        by_name = {row["dropbox_file_name"]: row for row in results}

        assert by_name["closed.jpg"]["staff_reviewed_at"] is not None
        assert by_name["closed.jpg"]["staff_review_needed"] is False
        assert by_name["untouched.jpg"]["staff_reviewed_at"] is None

    def test_a_cleared_image_still_comes_back_in_a_plain_search(self, client_logged_in, upload):
        """What a staff member does with the bulk Clear button, then goes looking for. The
        Filter row can only narrow what the server sent, so this is the half that has to hold
        server-side: a resolved image stays findable, carrying the timestamp the button reads.
        """
        image = make_search_image(upload, "cleared_by_bulk.jpg", staff_review_needed=True)

        client_logged_in.post(
            reverse("images:bulk_image_action"),
            {"image_ids[]": [str(image.id)], "action": "clear_flag"},
        )

        # Gone from the open queue, which is what clearing the flag means
        gone = json.loads(post_search(client_logged_in, staff_review_needed=True).content)["results"]
        assert gone == []

        found = json.loads(post_search(client_logged_in).content)["results"]
        assert [row["dropbox_file_name"] for row in found] == ["cleared_by_bulk.jpg"]
        assert found[0]["staff_reviewed_at"] is not None

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


@pytest.mark.django_db
class TestFlaggedByDisplay:
    """The Flagged by column's server-side name assembly."""

    def test_human_annotator_uses_name(self):
        row = {
            "flagged_by__type": "human",
            "flagged_by__human__name": "Ada Lovelace",
            "flagged_by__human__email": "ada@example.com",
            "flagged_by__bot__name": None,
        }
        assert flagged_by_display(row) == "Ada Lovelace"

    def test_human_annotator_falls_back_to_email(self):
        """User.name is optional, so a blank one must not render an empty cell."""
        row = {
            "flagged_by__type": "human",
            "flagged_by__human__name": "",
            "flagged_by__human__email": "ada@example.com",
            "flagged_by__bot__name": None,
        }
        assert flagged_by_display(row) == "ada@example.com"

    def test_bot_annotator_uses_bot_name(self):
        row = {
            "flagged_by__type": "bot",
            "flagged_by__human__name": None,
            "flagged_by__human__email": None,
            "flagged_by__bot__name": "MegaDetector",
        }
        assert flagged_by_display(row) == "MegaDetector"

    def test_unflagged_image_is_blank_not_none(self):
        """Auto-flagged and unflagged images have no annotator. The template joins this
        straight into a cell, so it must be a string rather than None."""
        row = {
            "flagged_by__type": None,
            "flagged_by__human__name": None,
            "flagged_by__human__email": None,
            "flagged_by__bot__name": None,
        }
        assert flagged_by_display(row) == ""


@pytest.mark.django_db
class TestReviewSessionAnchor:
    """The NEW badge cutoff, and when a review session rolls over."""

    def test_first_ever_visit_has_no_anchor(self, staff_user):
        """Nothing is NEW on a first visit -- every image is equally unseen."""
        assert review_session_anchor(staff_user) is None
        assert staff_user.last_review_visit_at is not None

    def test_anchor_holds_still_within_a_session(self, staff_user):
        """Searching repeatedly while working the queue must not move the cutoff, or the
        badges would clear themselves while they are being read."""
        review_session_anchor(staff_user)
        session_start = staff_user.last_review_visit_at

        for _ in range(3):
            assert review_session_anchor(staff_user) is None

        assert staff_user.last_review_visit_at == session_start

    def test_session_rolls_over_after_the_gap(self, staff_user):
        """A search after the idle gap starts a new session, and the previous session's start
        becomes the cutoff."""
        from django.utils import timezone

        review_session_anchor(staff_user)

        # Backdate the session so the next search falls outside the gap
        staff_user.last_review_visit_at = timezone.now() - (REVIEW_SESSION_GAP + timedelta(minutes=1))
        staff_user.save()
        first_session = staff_user.last_review_visit_at

        anchor = review_session_anchor(staff_user)

        assert anchor == first_session
        assert staff_user.last_review_visit_at > first_session

    def test_anchor_survives_a_reload_from_the_database(self, staff_user):
        """The side effect must be persisted, not just set on the in-memory instance."""
        from django.utils import timezone

        review_session_anchor(staff_user)
        staff_user.last_review_visit_at = timezone.now() - (REVIEW_SESSION_GAP + timedelta(minutes=1))
        staff_user.save()

        review_session_anchor(staff_user)
        staff_user.refresh_from_db()

        assert staff_user.previous_review_visit_at is not None


@pytest.mark.django_db
class TestSearchResultsNewBadge:
    """The NEW badge end to end through the search view."""

    def _flagged_image(self, upload, name, flagged_at):
        from django.utils import timezone

        return Image.objects.create(
            upload=upload,
            dropbox_file_name=f"{name}.jpg",
            dropbox_file_path=f"/test/{name}.jpg",
            dropbox_file_path_display=f"/test/{name}.jpg",
            dropbox_content_hash=f"hash_{name}",
            dropbox_file_id=f"file_id_{name}",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path=f"test/{name}_thumb.jpg",
            staff_review_needed=True,
            flag_source=StaffReviewFlagSource.MANUAL,
            flag_reason=StaffReviewFlagReason.SPECIES_ID,
            flagged_at=flagged_at,
        )

    def _search(self, client):
        url = reverse("images:search_images")
        response = client.post(
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
        return {r["dropbox_file_name"]: r for r in json.loads(response.content)["results"]}

    def test_nothing_is_new_on_a_first_visit(self, client_logged_in, staff_user, upload):
        from django.utils import timezone

        self._flagged_image(upload, "fresh", timezone.now())

        rows = self._search(client_logged_in)

        assert rows["fresh.jpg"]["is_new"] is False

    def test_image_flagged_since_the_last_session_is_new(self, client_logged_in, staff_user, upload):
        """The reviewer worked the queue yesterday; this image arrived afterwards."""
        from django.utils import timezone

        staff_user.previous_review_visit_at = timezone.now() - timedelta(days=1)
        staff_user.last_review_visit_at = timezone.now()
        staff_user.save()

        self._flagged_image(upload, "arrived_today", timezone.now())
        self._flagged_image(upload, "arrived_last_week", timezone.now() - timedelta(days=7))

        rows = self._search(client_logged_in)

        assert rows["arrived_today.jpg"]["is_new"] is True
        assert rows["arrived_last_week.jpg"]["is_new"] is False

    def test_legacy_flag_without_a_timestamp_is_never_new(self, client_logged_in, staff_user, upload):
        """Flags predating provenance have no flagged_at and must not be treated as recent."""
        from django.utils import timezone

        staff_user.previous_review_visit_at = timezone.now() - timedelta(days=1)
        staff_user.last_review_visit_at = timezone.now()
        staff_user.save()

        self._flagged_image(upload, "legacy", None)

        rows = self._search(client_logged_in)

        assert rows["legacy.jpg"]["is_new"] is False

    def test_badges_do_not_clear_on_a_second_search(self, client_logged_in, staff_user, upload):
        """The reviewer searches twice while working. The second search must still show NEW."""
        from django.utils import timezone

        staff_user.previous_review_visit_at = timezone.now() - timedelta(days=1)
        staff_user.last_review_visit_at = timezone.now()
        staff_user.save()

        self._flagged_image(upload, "arrived_today", timezone.now())

        assert self._search(client_logged_in)["arrived_today.jpg"]["is_new"] is True
        assert self._search(client_logged_in)["arrived_today.jpg"]["is_new"] is True


@pytest.mark.django_db
class TestSearchResultsFlaggedBy:
    """The Flagged by column end to end through the search view."""

    def _search_flagged(self, client):
        url = reverse("images:search_images")
        response = client.post(
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
        return json.loads(response.content)["results"]

    def _flagged_image(self, upload, name, **kwargs):
        from django.utils import timezone

        return Image.objects.create(
            upload=upload,
            dropbox_file_name=f"{name}.jpg",
            dropbox_file_path=f"/test/{name}.jpg",
            dropbox_file_path_display=f"/test/{name}.jpg",
            dropbox_content_hash=f"hash_{name}",
            dropbox_file_id=f"file_id_{name}",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path=f"test/{name}_thumb.jpg",
            staff_review_needed=True,
            **kwargs,
        )

    def test_manual_flag_returns_flagger_name(self, client_logged_in, upload):
        volunteer = User.objects.create_user(
            email="volunteer@example.com", password="testpass123", name="Grace Hopper"
        )
        annotator = Annotator.objects.create(type="human", human=volunteer)
        self._flagged_image(
            upload,
            "manual_flag",
            flag_source=StaffReviewFlagSource.MANUAL,
            flag_reason=StaffReviewFlagReason.SPECIES_ID,
            flagged_by=annotator,
        )

        results = self._search_flagged(client_logged_in)

        assert len(results) == 1
        assert results[0]["flagged_by_name"] == "Grace Hopper"

    def test_auto_flag_returns_blank_flagger(self, client_logged_in, upload):
        """Auto-flagged images have no one to attribute the flag to."""
        self._flagged_image(upload, "auto_flag", flag_source=StaffReviewFlagSource.AUTO_SKIPS)

        results = self._search_flagged(client_logged_in)

        assert len(results) == 1
        assert results[0]["flagged_by_name"] == ""

    def test_legacy_flag_without_provenance_returns_blank(self, client_logged_in, upload):
        """Flags predating provenance have no source and no flagger, and must not 500."""
        self._flagged_image(upload, "legacy_flag")

        results = self._search_flagged(client_logged_in)

        assert len(results) == 1
        assert results[0]["flagged_by_name"] == ""
