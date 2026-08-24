"""
Tests for a queue built from a search being served in the order the search was showing.

A many to many has no order of its own, so reading ImageQueue.images back falls through to
Image.Meta.ordering -- capture date. A staff member who sorted by flagger, or by newest first,
was served their batch oldest-capture-first regardless, and because a searched queue skips the
"already annotated by you" filter, it never moved off the first image either.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from images.models import Annotator, CameraStationAction, Image, ImageQueue, Upload
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
