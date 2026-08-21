"""
Tests for which queue an image lands in, given its flag and report state.

Every image must be reachable from exactly one of: the volunteer pool, the staff review queue,
or the reported images queue. An image that is both flagged and reported used to satisfy none
of them and disappeared from the site entirely.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from images.models import Annotator, CameraStationAction, Image, StaffReviewFlagSource, Upload
from images.views.annotation import CATEGORY_ANIMAL, activity_pipeline_query, species_pipeline_query
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def annotator(db):
    user = User.objects.create_user(email="routing@example.com", password="testpass123")
    return Annotator.objects.create(type="human", human=user)


@pytest.fixture
def upload(db):
    user = User.objects.create_user(email="routing-uploader@example.com", password="testpass123")
    area = Area.objects.create(name="Routing Area")
    county = County.objects.create(name="Routing County", area=area)
    macro_site = MacroSite.objects.create(name="Routing Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Routing Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="ROUTE001",
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
        dropbox_folder_name="routing_folder",
        dropbox_folder_path="/routing/folder",
        upload_method="E",
    )


def make_image(upload, name, *, flagged=False, reported=False):
    """An image eligible for both pipelines, in the requested flag/report state.

    Flagging goes through flag_for_staff_review() rather than setting the boolean, because the
    per-pipeline flags are what the pool queries actually consult -- setting staff_review_needed
    by hand produces a state no production code path can create.
    """
    image = Image.objects.create(
        upload=upload,
        dropbox_file_name=f"{name}.jpg",
        dropbox_file_path=f"/test/{name}.jpg",
        dropbox_file_path_display=f"/test/{name}.jpg",
        dropbox_content_hash=f"hash_{name}",
        dropbox_file_id=f"file_id_{name}",
        file_size=1024,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path=f"test/{name}_thumb.jpg",
        species_ai_detections="['Unknown']",
        image_reported=reported,
        # The species pipeline only considers preprocessed images that carry a confident
        # detection and still have species work outstanding.
        use_precomputed_flags=True,
        has_bbox_above_confidence_threshold=True,
        has_uncertain_bbox=True,
        # Also eligible for the activity pipeline, so a flag raised in one pipeline can be
        # shown to leave the other one alone.
        has_wild_animals=True,
        activity_pipeline_complete=False,
    )

    if flagged:
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

    return image


def queue_names(annotator, **kwargs):
    """File names visible in one of the three species queues."""
    images = species_pipeline_query(Image.objects.all(), annotator, **kwargs)

    return {i.dropbox_file_name for i in images}


def activity_queue_names(annotator, **kwargs):
    """The same, for the activity pipeline. Needed to show that a flag raised in one pipeline
    leaves the other alone."""
    images = activity_pipeline_query(Image.objects.all(), annotator, CATEGORY_ANIMAL, **kwargs)

    return {i.dropbox_file_name for i in images}


@pytest.mark.django_db
class TestQueueRouting:
    def test_a_plain_image_is_in_the_volunteer_pool_only(self, annotator, upload):
        make_image(upload, "plain")

        assert "plain.jpg" in queue_names(annotator)
        assert "plain.jpg" not in queue_names(annotator, staff_review=True)
        assert "plain.jpg" not in queue_names(annotator, reported_images=True)

    def test_a_flagged_image_is_in_the_staff_review_queue_only(self, annotator, upload):
        make_image(upload, "flagged", flagged=True)

        assert "flagged.jpg" in queue_names(annotator, staff_review=True)
        assert "flagged.jpg" not in queue_names(annotator)
        assert "flagged.jpg" not in queue_names(annotator, reported_images=True)

    def test_a_reported_image_is_in_the_reported_queue_only(self, annotator, upload):
        make_image(upload, "reported", reported=True)

        assert "reported.jpg" in queue_names(annotator, reported_images=True)
        assert "reported.jpg" not in queue_names(annotator)
        assert "reported.jpg" not in queue_names(annotator, staff_review=True)

    def test_an_image_both_flagged_and_reported_is_still_reachable(self, annotator, upload):
        """The two filters used to be applied independently, so this combination satisfied
        none of the three queues and the image vanished from the site."""
        make_image(upload, "both", flagged=True, reported=True)

        reachable = (
            "both.jpg" in queue_names(annotator)
            or "both.jpg" in queue_names(annotator, staff_review=True)
            or "both.jpg" in queue_names(annotator, reported_images=True)
        )

        assert reachable, "an image that is both flagged and reported is in no queue at all"

    def test_report_wins_over_flag(self, annotator, upload):
        """Reporting means "this does not belong in the pool", which is a stronger statement
        than "someone should look at this", so it decides where the image is triaged."""
        make_image(upload, "both", flagged=True, reported=True)

        assert "both.jpg" in queue_names(annotator, reported_images=True)
        assert "both.jpg" not in queue_names(annotator, staff_review=True)

    def test_a_staff_reviewed_image_never_returns_to_the_volunteer_pool(self, annotator, upload):
        """Once an image has been through staff review it is done with volunteers for good,
        however it got there. Staff can still hand it to an expert, which goes through an
        assigned queue rather than these filters."""
        image = make_image(upload, "reviewed", flagged=True)
        image.clear_staff_review_flag()

        assert "reviewed.jpg" not in queue_names(annotator)
        assert "reviewed.jpg" not in queue_names(annotator, staff_review=True)

    def test_an_unreviewed_image_is_still_in_the_pool(self, annotator, upload):
        """Guards the rule above against being written as "nothing is ever in the pool"."""
        make_image(upload, "untouched")

        assert "untouched.jpg" in queue_names(annotator)

    def test_a_species_flag_does_not_remove_the_image_from_the_activity_pool(self, annotator, upload):
        """The point of the per-pipeline flags. Nobody could name the animal, but knowing what
        it is doing does not require knowing what it is, so the activity pool keeps it."""
        image = make_image(upload, "species_only")
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS, pipelines=["species"])

        assert "species_only.jpg" not in queue_names(annotator)
        assert "species_only.jpg" in activity_queue_names(annotator)

    def test_an_activity_flag_does_not_remove_the_image_from_the_species_pool(self, annotator, upload):
        image = make_image(upload, "activity_only")
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS, pipelines=["activity"])

        assert "activity_only.jpg" in queue_names(annotator)
        assert "activity_only.jpg" not in activity_queue_names(annotator)

    def test_a_flag_in_either_pipeline_shows_in_the_staff_review_queue(self, annotator, upload):
        """Staff review is one list across pipelines -- staff want everything awaiting review,
        not one pipeline's share of it."""
        image = make_image(upload, "scoped")
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS, pipelines=["species"])

        assert "scoped.jpg" in queue_names(annotator, staff_review=True)

    def test_a_reported_image_never_reaches_volunteers(self, annotator, upload):
        """Whatever else is true of it, a reported image is out of the volunteer pool."""
        for name, flagged in [("reported_only", False), ("reported_and_flagged", True)]:
            make_image(upload, name, flagged=flagged, reported=True)

        pool = queue_names(annotator)

        assert "reported_only.jpg" not in pool
        assert "reported_and_flagged.jpg" not in pool
