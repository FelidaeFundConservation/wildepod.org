"""
Tests for a queue built from a search being served in the order the search was showing.

A many to many has no order of its own, so reading ImageQueue.images back falls through to
Image.Meta.ordering -- capture date. A staff member who sorted by flagger, or by newest first,
was served their batch oldest-capture-first regardless, and because a searched queue skips the
"already annotated by you" filter, it never moved off the first image either.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from images.models import Annotator, CameraStationAction, Image, ImageQueue, Upload
from images.views.annotation import SPECIES_QUEUE_NAME, get_precomputed_queue
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def upload(db):
    user = User.objects.create_user(email="order-uploader@example.com", password="testpass123")
    area = Area.objects.create(name="Order Area")
    county = County.objects.create(name="Order County", area=area)
    macro_site = MacroSite.objects.create(name="Order Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Order Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="ORDER001",
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
        dropbox_folder_name="order_folder",
        dropbox_folder_path="/order/folder",
        upload_method="E",
    )


@pytest.fixture
def annotator(db):
    user = User.objects.create_user(email="order-staff@example.com", password="testpass123", is_staff=True)
    return Annotator.objects.create(type="human", human=user)


def make_image(upload, name, days_old):
    """An image captured days_old days ago, so capture order can be set against search order."""
    from datetime import timedelta

    return Image.objects.create(
        upload=upload,
        dropbox_file_name=f"{name}.jpg",
        dropbox_file_path=f"/test/{name}.jpg",
        dropbox_file_path_display=f"/test/{name}.jpg",
        dropbox_content_hash=f"hash_{name}",
        dropbox_file_id=f"file_id_{name}",
        file_size=1024,
        trigger_timestamp=timezone.now() - timedelta(days=days_old),
        thumbnail_gcloud_path=f"test/{name}_thumb.jpg",
        species_ai_detections="['Unknown']",
    )


@pytest.fixture
def queue_in_reverse_capture_order(db, upload, annotator):
    """Three images queued newest-capture-first -- the opposite of Image.Meta.ordering, so any
    fall-through to the default ordering is immediately visible."""
    newest = make_image(upload, "newest", days_old=1)
    middle = make_image(upload, "middle", days_old=5)
    oldest = make_image(upload, "oldest", days_old=10)
    ordered = [newest, middle, oldest]

    queue = ImageQueue.objects.create(
        pipeline_name="Species",
        assigned_to=annotator,
        image_order=[str(image.id) for image in ordered],
    )
    queue.images.add(*ordered)

    return queue, ordered


@pytest.mark.django_db
class TestABuiltQueueSurvivesOrdinaryAnnotation:
    """A queue somebody built is not one the system may reclaim.

    get_precomputed_queue() frees an annotator's queues when it needs to hand them a new one.
    Assigned work is usually flagged, which fails the volunteer pool filters, so the batch
    reads as having nothing eligible and was swept along with the rest -- keeping its images
    and losing only its owner, which is exactly the kind of loss nobody reports, because from
    the expert's side there was simply never any work there.
    """

    def flagged_queue(self, upload, annotator):
        images = [make_image(upload, f"assigned_{index}", days_old=index + 1) for index in range(3)]
        Image.objects.filter(id__in=[image.id for image in images]).update(
            staff_review_needed=True, species_review_needed=True
        )

        queue = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        queue.add_images(images)

        return queue

    def test_ordinary_annotation_does_not_unassign_an_assigned_batch(self, db, upload, annotator):
        queue = self.flagged_queue(upload, annotator)

        # What clicking Classify -> Category & Species does before rendering anything
        get_precomputed_queue(queue_name=SPECIES_QUEUE_NAME, annotator=annotator, searched=False)

        queue.refresh_from_db()
        assert queue.assigned_to == annotator
        assert annotator not in queue.checked_by.all()

    def test_the_batch_is_still_what_the_searched_flow_serves(self, db, upload, annotator):
        """The other half: an annotator holding both kinds of queue must still be served the
        one built for them, not whichever the database returns first."""
        queue = self.flagged_queue(upload, annotator)
        ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)

        served = get_precomputed_queue(queue_name=SPECIES_QUEUE_NAME, annotator=annotator, searched=True)

        assert served == queue

    def test_an_automatic_queue_is_still_reclaimed(self, db, upload, annotator):
        """The sweep is exempting built queues, not switching itself off -- a precomputed queue
        with nothing left in it for this annotator still has to be released."""
        automatic = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        automatic.images.add(make_image(upload, "automatic", days_old=1))

        get_precomputed_queue(queue_name=SPECIES_QUEUE_NAME, annotator=annotator, searched=False)

        automatic.refresh_from_db()
        assert automatic.assigned_to is None


@pytest.mark.django_db
class TestOrderedImages:
    def test_images_come_back_in_search_order(self, queue_in_reverse_capture_order):
        queue, ordered = queue_in_reverse_capture_order

        assert [i.dropbox_file_name for i in queue.ordered_images()] == [
            "newest.jpg",
            "middle.jpg",
            "oldest.jpg",
        ]

    def test_the_related_manager_still_returns_capture_order(self, queue_in_reverse_capture_order):
        """Shows the two orders genuinely differ, so the test above is not passing by luck."""
        queue, _ = queue_in_reverse_capture_order

        assert [i.dropbox_file_name for i in queue.images.all()] == [
            "oldest.jpg",
            "middle.jpg",
            "newest.jpg",
        ]

    def test_a_queue_with_no_recorded_order_falls_back(self, db, upload, annotator):
        """Automatically precomputed queues have no search order and must still work."""
        image = make_image(upload, "auto", days_old=2)
        queue = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        queue.images.add(image)

        assert [i.dropbox_file_name for i in queue.ordered_images()] == ["auto.jpg"]

    def test_a_deleted_image_is_skipped(self, queue_in_reverse_capture_order):
        """image_order holds ids, so one going away must not break the queue."""
        queue, ordered = queue_in_reverse_capture_order
        ordered[1].delete()

        assert [i.dropbox_file_name for i in queue.ordered_images()] == ["newest.jpg", "oldest.jpg"]


@pytest.mark.django_db
class TestAdvancing:
    def test_advancing_moves_past_the_given_image(self, queue_in_reverse_capture_order):
        queue, ordered = queue_in_reverse_capture_order

        assert queue.advance_past(ordered[0].id) is True

        queue.refresh_from_db()
        assert queue.position == 1
        assert queue.ordered_images()[queue.position].dropbox_file_name == "middle.jpg"

    def test_advancing_is_keyed_off_the_image_not_a_counter(self, queue_in_reverse_capture_order):
        """Someone can jump around the queue with the grid, so the cursor follows whatever was
        actually annotated rather than simply incrementing."""
        queue, ordered = queue_in_reverse_capture_order

        queue.advance_past(ordered[2].id)

        queue.refresh_from_db()
        assert queue.position == 3

    def test_advancing_past_an_image_not_in_the_queue_does_nothing(self, queue_in_reverse_capture_order, upload):
        queue, _ = queue_in_reverse_capture_order
        stranger = make_image(upload, "stranger", days_old=3)

        assert queue.advance_past(stranger.id) is False

        queue.refresh_from_db()
        assert queue.position == 0

    def test_a_queue_with_no_order_cannot_advance(self, db, upload, annotator):
        image = make_image(upload, "auto", days_old=2)
        queue = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        queue.images.add(image)

        assert queue.advance_past(image.id) is False

    def test_working_through_the_whole_queue_terminates(self, queue_in_reverse_capture_order):
        """The stuck-on-the-first-image bug: a searched queue skips the "annotated by you"
        filter, so without the cursor the same image is served for ever."""
        queue, ordered = queue_in_reverse_capture_order
        served = []

        for _ in range(len(ordered) + 1):
            remaining = queue.ordered_images()[queue.position :]
            if not remaining:
                break

            served.append(remaining[0].dropbox_file_name)
            queue.advance_past(remaining[0].id)
            queue.refresh_from_db()

        assert served == ["newest.jpg", "middle.jpg", "oldest.jpg"]


@pytest.mark.django_db
class TestMovingTo:
    """move_to is the grid's counterpart to advance_past: "show me this one", not "next"."""

    def test_moving_to_an_image_serves_that_image(self, queue_in_reverse_capture_order):
        queue, ordered = queue_in_reverse_capture_order

        assert queue.move_to(ordered[2].id) is True

        queue.refresh_from_db()
        assert queue.position == 2
        assert queue.ordered_images()[queue.position].dropbox_file_name == "oldest.jpg"

    def test_moving_to_an_image_can_go_backwards(self, queue_in_reverse_capture_order):
        """Half the point of the grid is going back for one you passed."""
        queue, ordered = queue_in_reverse_capture_order
        queue.advance_past(ordered[2].id)

        assert queue.move_to(ordered[0].id) is True

        queue.refresh_from_db()
        assert queue.position == 0

    def test_moving_to_an_image_not_in_the_queue_does_nothing(self, queue_in_reverse_capture_order, upload):
        queue, _ = queue_in_reverse_capture_order
        stranger = make_image(upload, "stranger", days_old=3)

        assert queue.move_to(stranger.id) is False

        queue.refresh_from_db()
        assert queue.position == 0

    def test_a_queue_with_no_order_cannot_move(self, db, upload, annotator):
        image = make_image(upload, "auto", days_old=2)
        queue = ImageQueue.objects.create(pipeline_name="Species", assigned_to=annotator)
        queue.images.add(image)

        assert queue.move_to(image.id) is False


@pytest.mark.django_db
class TestMoveSearchedQueueCursorView:
    """The endpoint behind the Next button and the grid, which move the cursor and nothing
    else -- unlike Skip, which records the annotator on the image's skipped list."""

    def _login(self, annotator):
        client = Client()
        client.force_login(annotator.human)

        return client

    def test_next_advances_past_the_current_image(self, queue_in_reverse_capture_order, annotator):
        queue, ordered = queue_in_reverse_capture_order
        client = self._login(annotator)

        response = client.post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(ordered[0].id), "mode": "past"},
        )

        assert response.json() == {"success": True, "position": 1, "total": 3}
        queue.refresh_from_db()
        assert queue.position == 1

    def test_the_grid_jumps_straight_to_an_image(self, queue_in_reverse_capture_order, annotator):
        queue, ordered = queue_in_reverse_capture_order
        client = self._login(annotator)

        response = client.post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(ordered[2].id), "mode": "at"},
        )

        assert response.json()["success"] is True
        queue.refresh_from_db()
        assert queue.position == 2

    def test_moving_on_records_nothing_about_the_image(self, queue_in_reverse_capture_order, annotator):
        """The whole reason this is not the skip path: a staff member paging through a batch
        they assembled must not count towards the automatic review flag."""
        _, ordered = queue_in_reverse_capture_order
        client = self._login(annotator)

        client.post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(ordered[0].id), "mode": "past"},
        )

        ordered[0].refresh_from_db()
        assert ordered[0].species_skipped_by.count() == 0
        assert ordered[0].staff_review_needed is False

    def test_an_image_outside_the_queue_is_refused(self, queue_in_reverse_capture_order, annotator, upload):
        queue, _ = queue_in_reverse_capture_order
        stranger = make_image(upload, "stranger", days_old=3)
        client = self._login(annotator)

        response = client.post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(stranger.id), "mode": "past"},
        )

        assert response.json()["success"] is False
        queue.refresh_from_db()
        assert queue.position == 0

    def test_an_annotator_with_no_searched_queue_is_refused(self, db, upload, annotator):
        image = make_image(upload, "loose", days_old=2)
        client = self._login(annotator)

        response = client.post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(image.id), "mode": "past"},
        )

        assert response.json()["success"] is False

    def test_login_is_required(self, queue_in_reverse_capture_order):
        _, ordered = queue_in_reverse_capture_order

        response = Client().post(
            reverse("images:move_searched_queue_cursor"),
            {"image_id": str(ordered[0].id), "mode": "past"},
        )

        assert response.status_code == 302
