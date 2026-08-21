"""
Tests for who can reach the privileged annotation queues.

The nav links to the staff review and reported images queues are hidden behind is_staff /
is_expert, but a hidden link is not a permission check: the URLs can be typed. These tests ask
what actually happens when a plain volunteer does exactly that.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from images.models import Annotator, CameraStationAction, Image, StaffReviewFlagSource, Upload
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()

# The routes that are meant to be for staff, and the queue each one opens
PRIVILEGED_ROUTES = [
    "images:staff_annotate_species",
    "images:reported_images_annotate_species",
    "images:searched_annotate_species",
]


@pytest.fixture
def upload(db):
    user = User.objects.create_user(email="perm-uploader@example.com", password="testpass123")
    area = Area.objects.create(name="Perm Area")
    county = County.objects.create(name="Perm County", area=area)
    macro_site = MacroSite.objects.create(name="Perm Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Perm Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="PERM001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        date_deployed=timezone.now().date(),
    )
    action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")

    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="perm_folder",
        dropbox_folder_path="/perm/folder",
        upload_method="E",
    )


@pytest.fixture
def flagged_image(db, upload):
    """An image sitting in the staff review queue, with a volunteer's name attached to it."""
    volunteer = User.objects.create_user(
        email="perm-flagger@example.com", password="testpass123", name="Frankie Flagger"
    )
    annotator = Annotator.objects.create(type="human", human=volunteer)

    image = Image.objects.create(
        upload=upload,
        dropbox_file_name="sensitive.jpg",
        dropbox_file_path="/test/sensitive.jpg",
        dropbox_file_path_display="/test/sensitive.jpg",
        dropbox_content_hash="hash_sensitive",
        dropbox_file_id="file_id_sensitive",
        file_size=1024,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path="test/sensitive_thumb.jpg",
        species_ai_detections="['Unknown']",
        use_precomputed_flags=True,
        has_bbox_above_confidence_threshold=True,
        has_uncertain_bbox=True,
    )
    image.flag_for_staff_review(
        source=StaffReviewFlagSource.MANUAL, annotator=annotator, reason="species_id"
    )

    return image


@pytest.fixture
def volunteer_client(db):
    """A logged-in user who is neither staff nor expert."""
    user = User.objects.create_user(email="perm-volunteer@example.com", password="testpass123")
    client = Client()
    client.force_login(user)

    return client


@pytest.mark.django_db
class TestPrivilegedRoutesRequireLogin:
    @pytest.mark.parametrize("route", PRIVILEGED_ROUTES)
    def test_anonymous_is_redirected(self, client, route):
        response = client.get(reverse(route))

        assert response.status_code == 302
        assert "login" in response.url


@pytest.mark.django_db
class TestPrivilegedRoutesRefuseVolunteers:
    """A logged-in volunteer typing the URL must not get the staff queue."""

    @pytest.mark.parametrize("route", PRIVILEGED_ROUTES)
    def test_a_volunteer_is_refused(self, volunteer_client, flagged_image, route):
        response = volunteer_client.get(reverse(route))

        assert response.status_code in (302, 403), (
            f"{route} served a volunteer HTTP {response.status_code}; the nav link is hidden "
            f"but the URL is not gated"
        )

    def test_a_volunteer_is_not_served_a_flagged_image(self, volunteer_client, flagged_image):
        """The sharper question: whatever the status code, does the flagged image come back?"""
        response = volunteer_client.get(reverse("images:staff_annotate_species"))

        served = getattr(response, "context", None) and response.context.get("image")

        assert served is None or served.id != flagged_image.id, (
            "a volunteer was served an image from the staff review queue"
        )


@pytest.mark.django_db
class TestStaffAndExpertsAreStillLetIn:
    """The gate must not lock out the people it is for."""

    def test_staff_reach_the_staff_review_queue(self, db, flagged_image):
        staff = User.objects.create_user(
            email="perm-staff@example.com", password="testpass123", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        response = client.get(reverse("images:staff_annotate_species"))

        assert response.status_code == 200

    def test_experts_reach_their_assigned_queue(self, db, flagged_image):
        expert = User.objects.create_user(
            email="perm-expert@example.com", password="testpass123", is_expert=True
        )
        client = Client()
        client.force_login(expert)

        response = client.get(reverse("images:searched_annotate_species"))

        assert response.status_code == 200
