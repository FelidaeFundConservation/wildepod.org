"""
Tests for the automatic skip-threshold flag, and for it not undoing staff's work.

The skip counters never reset, so once an image is past the threshold every later skip
satisfies it again. Without a record of staff having dealt with the image, clearing the flag
only lasts until the next volunteer skips it.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from images.models import Annotator, CameraStationAction, Image, StaffReviewFlagSource, Upload
from images.views.annotation import auto_flag_for_staff
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def upload(db):
    user = User.objects.create_user(email="retrigger-uploader@example.com", password="testpass123")
    area = Area.objects.create(name="Retrigger Area")
    county = County.objects.create(name="Retrigger County", area=area)
    macro_site = MacroSite.objects.create(name="Retrigger Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Retrigger Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="RETRIG001",
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
        dropbox_folder_name="retrigger_folder",
        dropbox_folder_path="/retrigger/folder",
        upload_method="E",
    )


@pytest.fixture
def image(db, upload):
    return Image.objects.create(
        upload=upload,
        dropbox_file_name="skipped.jpg",
        dropbox_file_path="/test/skipped.jpg",
        dropbox_file_path_display="/test/skipped.jpg",
        dropbox_content_hash="hash_skipped",
        dropbox_file_id="file_id_skipped",
        file_size=1024,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path="test/skipped_thumb.jpg",
    )


def skip_by(image, n, start=0):
    """Has n more volunteers skip the image in the species pipeline."""
    for i in range(start, start + n):
        user = User.objects.create_user(email=f"skipper{i}@example.com", password="testpass123")
        annotator = Annotator.objects.create(type="human", human=user)
        image.species_skipped_by.add(annotator)

    return image


@pytest.mark.django_db
class TestAutoFlagThreshold:
    def test_two_skips_do_not_flag(self, image):
        skip_by(image, 2)

        assert auto_flag_for_staff(image) is False
        assert image.staff_review_needed is False

    def test_the_third_skip_flags(self, image):
        skip_by(image, 3)

        assert auto_flag_for_staff(image) is True

        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_source == StaffReviewFlagSource.AUTO_SKIPS

    def test_a_deliberate_flag_is_not_overwritten_by_the_automatic_one(self, image):
        """An annotator's reason must survive the threshold being crossed later."""
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")
        skip_by(image, 3)

        auto_flag_for_staff(image)

        image.refresh_from_db()
        assert image.flag_source == StaffReviewFlagSource.MANUAL
        assert image.flag_reason == "species_id"


@pytest.mark.django_db
class TestAnnotatingClearsTheFlag:
    """Staff expect a reviewed image to leave the list. It has to leave for whoever reviewed
    it -- including an expert working through a batch that staff assigned to them."""

    def _annotate(self, reviewer, image):
        from django.test import Client
        from django.urls import reverse

        client = Client()
        client.force_login(reviewer)

        return client.post(
            reverse("images:species_annotation_processor"),
            {
                "image_id": str(image.id),
                "skip": "false",
                "annotations": "{}",
                "initial_bboxes": "{}",
                "social_media_worthy_vote": "0",
                # The submit path sends the checkbox unticked when the reviewer is not
                # re-flagging, which is what asks for the flag to be cleared.
                "staff_review_needed": "false",
            },
        )

    def test_a_staff_member_annotating_clears_the_flag(self, image):
        staff = User.objects.create_user(
            email="clearing-staff@example.com", password="testpass123", is_staff=True
        )
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

        self._annotate(staff, image)

        image.refresh_from_db()
        assert image.staff_review_needed is False

    def test_an_expert_annotating_clears_the_flag(self, image):
        """Bulk assignment hands flagged work to experts, who are not staff. Without this the
        expert does the work and the image stays in the review list for ever."""
        expert = User.objects.create_user(
            email="clearing-expert@example.com", password="testpass123", is_expert=True
        )
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

        self._annotate(expert, image)

        image.refresh_from_db()
        assert image.staff_review_needed is False, "an expert reviewed it but it stayed flagged"

    def test_an_ordinary_volunteer_does_not_clear_the_flag(self, image):
        """Guards the rule above from becoming "anyone annotating clears it"."""
        volunteer = User.objects.create_user(email="clearing-vol@example.com", password="testpass123")
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

        self._annotate(volunteer, image)

        image.refresh_from_db()
        assert image.staff_review_needed is True


@pytest.mark.django_db
class TestFlagIsScopedToThePipelineThatRanOut:
    """The threshold is counted per pipeline, so the flag it raises must be too."""

    def test_species_skips_flag_only_the_species_pipeline(self, image):
        """Three volunteers could not say what the animal is. That says nothing about whether
        anyone can say what it is doing."""
        skip_by(image, 3)

        auto_flag_for_staff(image)

        image.refresh_from_db()
        assert image.species_review_needed is True
        assert image.activity_review_needed is False
        assert image.staff_review_needed is True

    def test_activity_skips_flag_only_the_activity_pipeline(self, image):
        for i in range(3):
            user = User.objects.create_user(email=f"act{i}@example.com", password="testpass123")
            image.activity_skipped_by.add(Annotator.objects.create(type="human", human=user))

        auto_flag_for_staff(image)

        image.refresh_from_db()
        assert image.activity_review_needed is True
        assert image.species_review_needed is False

    def test_a_deliberate_flag_covers_every_pipeline(self, image):
        """An annotator ticking the box is asking staff to look at the image, not at one
        pipeline's worth of it."""
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

        image.refresh_from_db()
        assert image.species_review_needed is True
        assert image.activity_review_needed is True

    def test_clearing_the_flag_clears_every_pipeline(self, image):
        skip_by(image, 3)
        auto_flag_for_staff(image)

        image.refresh_from_db()
        image.clear_staff_review_flag()

        image.refresh_from_db()
        assert image.species_review_needed is False
        assert image.activity_review_needed is False
        assert image.staff_review_needed is False


@pytest.mark.django_db
class TestStaffReviewIsNotUndone:
    def test_a_reviewed_image_is_not_flagged_again_by_the_next_skip(self, image):
        """The loop: three volunteers skip, staff resolve it, and the very next volunteer to
        skip sends it straight back to staff because the counter still reads three."""
        skip_by(image, 3)
        auto_flag_for_staff(image)

        # Staff deal with it
        image.clear_staff_review_flag()

        # A fourth volunteer skips
        skip_by(image, 1, start=3)

        assert auto_flag_for_staff(image) is False, "staff review was undone by the next skip"

        image.refresh_from_db()
        assert image.staff_review_needed is False

    def test_clearing_the_flag_records_that_staff_reviewed_it(self, image):
        assert image.staff_reviewed_at is None

        image.clear_staff_review_flag()

        image.refresh_from_db()
        assert image.staff_reviewed_at is not None

    def test_a_volunteer_can_still_deliberately_flag_a_reviewed_image(self, image):
        """Only the automatic path is suppressed. A person asking for help is a new request,
        not the counter tripping again."""
        skip_by(image, 3)
        auto_flag_for_staff(image)
        image.clear_staff_review_flag()

        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL, reason="species_id")

        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_source == StaffReviewFlagSource.MANUAL

    def test_an_image_staff_never_saw_still_auto_flags(self, image):
        """The suppression must be tied to staff having dealt with it, not merely to the flag
        being absent, or the threshold would never fire at all."""
        skip_by(image, 3)

        assert auto_flag_for_staff(image) is True
