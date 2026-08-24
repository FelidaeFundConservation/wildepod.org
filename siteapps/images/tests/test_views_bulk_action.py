"""
Tests for the bulk image action endpoint used by the staff search results table.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from images.models import (
    Annotator,
    CameraStationAction,
    Image,
    ImageQueue,
    StaffReviewFlagReason,
    StaffReviewFlagSource,
    Upload,
)
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(email="bulkstaff@example.com", password="testpass123", is_staff=True)


@pytest.fixture
def client_logged_in(staff_user):
    client = Client()
    client.force_login(staff_user)
    return client


@pytest.fixture
def expert(db):
    return User.objects.create_user(
        email="expert@example.com", password="testpass123", name="Ellie Expert", is_expert=True
    )


@pytest.fixture
def upload(db, staff_user):
    from django.utils import timezone

    area = Area.objects.create(name="Bulk Area")
    county = County.objects.create(name="Bulk County", area=area)
    macro_site = MacroSite.objects.create(name="Bulk Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Bulk Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="BULK001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        date_deployed=timezone.now().date(),
    )
    action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")

    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=staff_user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="bulk_folder",
        dropbox_folder_path="/bulk/folder",
        upload_method="E",
    )


def make_flagged_image(upload, name, flagger=None):
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
        # Cached species inference, as every image uploaded since Feb 2024 has. Without it the
        # annotate view calls out to the detection model, which is not something a test of the
        # review queue should be reaching for.
        species_ai_detections="['Unknown']",
        staff_review_needed=True,
        flag_source=StaffReviewFlagSource.MANUAL,
        flag_reason=StaffReviewFlagReason.SPECIES_ID,
        flagged_by=flagger,
        flagged_at=timezone.now(),
    )


def post_action(client, action, image_ids, **extra):
    return client.post(
        reverse("images:bulk_image_action"),
        {"action": action, "image_ids[]": [str(i) for i in image_ids], **extra},
    )


@pytest.mark.django_db
class TestBulkActionPermissions:
    def test_anonymous_is_redirected(self, client, upload):
        image = make_flagged_image(upload, "anon")

        response = post_action(client, "clear_flag", [image.id])

        assert response.status_code == 302
        image.refresh_from_db()
        assert image.staff_review_needed is True

    def test_non_staff_is_refused(self, db, upload):
        """A logged-in volunteer must not be able to clear flags in bulk. This also covers the
        braces/AccessMixin signature mismatch, which would surface as a 500 rather than a 302."""
        volunteer = User.objects.create_user(email="volunteer@example.com", password="testpass123")
        client = Client()
        client.force_login(volunteer)
        image = make_flagged_image(upload, "volunteer")

        response = post_action(client, "clear_flag", [image.id])

        assert response.status_code in (302, 403)
        image.refresh_from_db()
        assert image.staff_review_needed is True


@pytest.mark.django_db
class TestBulkActionValidation:
    def test_no_images_selected_is_rejected(self, client_logged_in):
        response = client_logged_in.post(reverse("images:bulk_image_action"), {"action": "clear_flag"})

        assert response.status_code == 400
        assert json.loads(response.content)["success"] is False

    def test_unknown_action_is_rejected(self, client_logged_in, upload):
        image = make_flagged_image(upload, "unknown_action")

        response = post_action(client_logged_in, "delete_everything", [image.id])

        assert response.status_code == 400
        image.refresh_from_db()
        assert image.staff_review_needed is True


@pytest.mark.django_db
class TestBulkClearFlag:
    def test_clears_the_flag_and_all_provenance(self, client_logged_in, upload, expert):
        flagger = Annotator.objects.create(type="human", human=expert)
        image = make_flagged_image(upload, "clear_me", flagger=flagger)

        response = post_action(client_logged_in, "clear_flag", [image.id])

        assert response.status_code == 200
        assert json.loads(response.content)["count"] == 1

        image.refresh_from_db()
        assert image.staff_review_needed is False
        assert image.flag_source == ""
        assert image.flag_reason == ""
        assert image.flag_reason_detail == ""
        assert image.flagged_by is None
        assert image.flagged_at is None

    def test_clears_every_field_the_model_calls_cleared(self, client_logged_in, upload):
        """Guards against the bulk path and clear_staff_review_flag() drifting apart when a
        new provenance field is added to one but not the other."""
        image = make_flagged_image(upload, "all_fields")

        post_action(client_logged_in, "clear_flag", [image.id])

        image.refresh_from_db()
        for field, expected in Image.CLEARED_STAFF_REVIEW_FIELDS.items():
            assert getattr(image, field) == expected, f"{field} was not cleared"

    def test_touches_only_the_selected_images(self, client_logged_in, upload):
        selected = make_flagged_image(upload, "selected")
        untouched = make_flagged_image(upload, "untouched")

        post_action(client_logged_in, "clear_flag", [selected.id])

        selected.refresh_from_db()
        untouched.refresh_from_db()
        assert selected.staff_review_needed is False
        assert untouched.staff_review_needed is True


@pytest.mark.django_db
class TestBulkAssignExpert:
    def test_assigns_images_to_the_expert_queue(self, client_logged_in, upload, expert):
        images = [make_flagged_image(upload, f"assign_{i}") for i in range(3)]

        response = post_action(
            client_logged_in, "assign_expert", [i.id for i in images], expert_id=str(expert.id)
        )

        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["count"] == 3

        annotator = Annotator.objects.get(human=expert)
        queue = ImageQueue.objects.get(assigned_to=annotator)
        assert queue.images.count() == 3

    def test_a_second_assignment_appends_rather_than_replacing(self, client_logged_in, upload, expert):
        """Two staff assigning work to the same expert must not destroy each other's batch."""
        first = [make_flagged_image(upload, f"first_{i}") for i in range(2)]
        second = [make_flagged_image(upload, f"second_{i}") for i in range(3)]

        post_action(client_logged_in, "assign_expert", [i.id for i in first], expert_id=str(expert.id))
        post_action(client_logged_in, "assign_expert", [i.id for i in second], expert_id=str(expert.id))

        annotator = Annotator.objects.get(human=expert)
        queues = ImageQueue.objects.filter(assigned_to=annotator)

        assert queues.count() == 1, "a second assignment should reuse the expert's queue"
        assert queues.first().images.count() == 5

    def test_appending_resets_the_partition(self, client_logged_in, upload, expert):
        """partition excludes images before it, so appended images would otherwise be invisible.

        Asserted as "excludes nothing" rather than "equals datetime.min": the codebase stores a
        naive datetime.min there, which comes back from the database shifted by the local
        timezone offset. What matters is that the appended image is no longer cut off.
        """
        from django.utils import timezone

        annotator = Annotator.objects.create(type="human", human=expert)
        queue = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        queue.partition = timezone.now()
        queue.save()

        image = make_flagged_image(upload, "appended")
        post_action(client_logged_in, "assign_expert", [image.id], expert_id=str(expert.id))

        queue.refresh_from_db()
        assert queue.partition.year == 1
        assert queue.partition <= image.trigger_timestamp

    def test_a_non_expert_is_rejected(self, client_logged_in, upload, staff_user):
        """Only users flagged as experts can be assigned review work."""
        image = make_flagged_image(upload, "not_expert")

        response = post_action(
            client_logged_in, "assign_expert", [image.id], expert_id=str(staff_user.id)
        )

        assert response.status_code == 400
        assert ImageQueue.objects.count() == 0

    def test_a_malformed_expert_id_is_rejected_not_a_500(self, client_logged_in, upload):
        image = make_flagged_image(upload, "bad_uuid")

        response = post_action(client_logged_in, "assign_expert", [image.id], expert_id="not-a-uuid")

        assert response.status_code == 400

    def test_assigning_to_an_expert_who_already_has_a_search_queue(self, client_logged_in, upload, expert):
        """A queue built from a search records its order, and only what that order lists is
        ever served. Images added straight to the many to many would be in the queue but
        invisible, so the assignment would silently deliver nothing."""
        annotator = Annotator.objects.create(type="human", human=expert)
        own_search = [make_flagged_image(upload, f"theirs_{i}") for i in range(2)]
        queue = ImageQueue.objects.create(
            pipeline_name="Species",
            assigned_to=annotator,
            image_order=[str(i.id) for i in own_search],
        )
        queue.images.add(*own_search)

        assigned = [make_flagged_image(upload, f"assigned_{i}") for i in range(3)]
        post_action(client_logged_in, "assign_expert", [i.id for i in assigned], expert_id=str(expert.id))

        queue.refresh_from_db()
        served = {i.dropbox_file_name for i in queue.ordered_images()}

        assert queue.images.count() == 5
        assert len(queue.ordered_images()) == 5, "assigned images are in the queue but never served"
        assert {"assigned_0.jpg", "assigned_1.jpg", "assigned_2.jpg"} <= served

    def test_assigned_images_land_after_work_already_done(self, client_logged_in, upload, expert):
        """The expert had finished their own search. New work must be reachable, not stranded
        behind a cursor that is already at the end."""
        annotator = Annotator.objects.create(type="human", human=expert)
        own_search = [make_flagged_image(upload, f"done_{i}") for i in range(2)]
        queue = ImageQueue.objects.create(
            pipeline_name="Species",
            assigned_to=annotator,
            image_order=[str(i.id) for i in own_search],
            position=2,
        )
        queue.images.add(*own_search)

        assigned = make_flagged_image(upload, "new_work")
        post_action(client_logged_in, "assign_expert", [assigned.id], expert_id=str(expert.id))

        queue.refresh_from_db()
        remaining = queue.ordered_images()[queue.position :]

        assert [i.dropbox_file_name for i in remaining] == ["new_work.jpg"]

    def test_the_expert_can_actually_see_the_work(self, client_logged_in, upload, expert):
        """Assigning is only useful if it arrives. Logs in as the expert and asks for the
        annotation queue their assignment went to."""
        images = [make_flagged_image(upload, f"work_{i}") for i in range(3)]
        post_action(client_logged_in, "assign_expert", [i.id for i in images], expert_id=str(expert.id))

        expert_client = Client()
        expert_client.force_login(expert)
        response = expert_client.get(reverse("images:searched_annotate_species"))

        assert response.status_code == 200
        assert response.context["image"] is not None, "the expert was served no image at all"
        assert response.context["image"].id in {i.id for i in images}

    def test_assigning_leaves_the_staff_review_flag_alone(self, client_logged_in, upload, expert):
        """Handing work to an expert is not the same as resolving it -- the flag stays until
        someone actually reviews the image."""
        image = make_flagged_image(upload, "still_flagged")

        post_action(client_logged_in, "assign_expert", [image.id], expert_id=str(expert.id))

        image.refresh_from_db()
        assert image.staff_review_needed is True
