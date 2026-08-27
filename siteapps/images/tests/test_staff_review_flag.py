# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Test suite for the "Flag for Staff Review" pipeline.

Covers ``images.views.annotation.annotation_processor`` flag handling,
``images.views.annotation.auto_flag_for_staff`` and the provenance helpers on
``images.models.Image``.

Behaviour these tests pin down:
- Any annotator (not just staff) can flag, but only with a reason.
- A reasonless or unrecognised reason is rejected; the flag is not set.
- A staff member who ticks the box keeps the flag; one who does not clears it.
- A submission that omits the field entirely preserves the existing flag.
- Auto-flagging is recorded as such and never overwrites a deliberate flag.
"""

import json
from unittest.mock import patch

import pytest
from conftest_factories import AnnotatorFactory, ImageFactory
from django.urls import reverse
from images.models import Image, StaffReviewFlagReason, StaffReviewFlagSource
from images.views.annotation import auto_flag_for_staff


@pytest.fixture
def fake_datastore():
    """The annotation processor writes queue state to Datastore, absent in tests.

    Kept so the tests below say what they depend on, but the stub now lives in the test
    tree rather than in local settings, which are per developer and not committed -- so
    importing it from there passed locally and failed for everyone else.
    """
    from images.tests.datastore_stub import LocalDatastoreClient

    with patch("django.conf.settings.DATASTORE_CLIENT", LocalDatastoreClient()):
        yield


def post_annotation(client, image, **overrides):
    """POSTs a minimal, valid species annotation payload for ``image``."""
    payload = {
        "image_id": str(image.id),
        "skip": "false",
        "is_reannotation": "False",
        "initial_bboxes": json.dumps([]),
        "annotations": json.dumps([]),
        "social_media_worthy_vote": "0",
        "batch_tag_images": json.dumps([]),
        "custom_annotations": "False",
        "staff_review": "False",
        "reported_images": "False",
    }
    payload.update(overrides)

    return client.post(reverse("images:species_annotation_processor"), payload)


@pytest.mark.django_db
class TestFlagRequiresReason:
    """A deliberate flag must say why, so it stays a signal rather than a shrug."""

    def test_volunteer_can_flag_with_a_reason(self, client, user, image, fake_datastore):
        client.force_login(user)

        response = post_annotation(
            client,
            image,
            staff_review_needed="true",
            staff_review_reason=StaffReviewFlagReason.SPECIES_ID,
        )

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_reason == StaffReviewFlagReason.SPECIES_ID
        assert image.flag_source == StaffReviewFlagSource.MANUAL
        assert image.flagged_by.human == user
        assert image.flagged_at is not None

    def test_flag_without_a_reason_is_rejected(self, client, user, image, fake_datastore):
        client.force_login(user)

        response = post_annotation(client, image, staff_review_needed="true")

        assert response.status_code == 400
        image.refresh_from_db()
        assert image.staff_review_needed is False
        assert image.flag_reason == ""

    def test_flag_with_unrecognised_reason_is_rejected(self, client, user, image, fake_datastore):
        client.force_login(user)

        response = post_annotation(
            client,
            image,
            staff_review_needed="true",
            staff_review_reason="because_i_said_so",
        )

        assert response.status_code == 400
        image.refresh_from_db()
        assert image.staff_review_needed is False

    def test_other_reason_stores_free_text_detail(self, client, user, image, fake_datastore):
        client.force_login(user)

        response = post_annotation(
            client,
            image,
            staff_review_needed="true",
            staff_review_reason=StaffReviewFlagReason.OTHER,
            staff_review_reason_detail="Two cameras triggered at once",
        )

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.flag_reason == StaffReviewFlagReason.OTHER
        assert image.flag_reason_detail == "Two cameras triggered at once"


@pytest.mark.django_db
class TestStaffFlagIsNotDiscarded:
    """Staff reviewing an image clears the flag, unless they just asked for review."""

    def test_staff_ticking_the_box_keeps_the_flag(self, client, staff_user, image, fake_datastore):
        """Regression: the staff auto-unflag used to overwrite the tick in the same request."""
        client.force_login(staff_user)

        response = post_annotation(
            client,
            image,
            staff_review_needed="true",
            staff_review_reason=StaffReviewFlagReason.SPECIES_ID,
        )

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_reason == StaffReviewFlagReason.SPECIES_ID

    def test_staff_saving_without_ticking_clears_the_flag(self, client, staff_user, fake_datastore):
        image = ImageFactory()
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)
        client.force_login(staff_user)

        response = post_annotation(client, image, staff_review_needed="false")

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is False
        # Provenance is cleared alongside the flag
        assert image.flag_source == ""
        assert image.flagged_by is None
        assert image.flagged_at is None


@pytest.mark.django_db
class TestOmittedFieldPreservesFlag:
    def test_submission_without_the_field_leaves_the_flag_alone(self, client, user, fake_datastore):
        """A page that never rendered the checkbox must not silently clear the flag."""
        image = ImageFactory()
        annotator = AnnotatorFactory()
        image.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=annotator,
            reason=StaffReviewFlagReason.BBOX_PROTOCOL,
        )
        client.force_login(user)

        # staff_review_needed deliberately absent from the payload
        response = post_annotation(client, image)

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_reason == StaffReviewFlagReason.BBOX_PROTOCOL


@pytest.mark.django_db
class TestAutoFlagging:
    def _skip_image_n_times(self, image, times):
        for _ in range(times):
            image.species_skipped_by.add(AnnotatorFactory())

    def test_auto_flag_does_not_fire_below_threshold(self, image):
        self._skip_image_n_times(image, 2)

        assert auto_flag_for_staff(image) is False
        image.refresh_from_db()
        assert image.staff_review_needed is False

    def test_auto_flag_fires_above_threshold_and_records_source(self, image):
        self._skip_image_n_times(image, 3)

        assert auto_flag_for_staff(image) is True
        image.refresh_from_db()
        assert image.staff_review_needed is True
        assert image.flag_source == StaffReviewFlagSource.AUTO_SKIPS
        # Nobody asked for this review, so there is no reason and no flagger
        assert image.flag_reason == ""
        assert image.flagged_by is None

    def test_auto_flag_does_not_overwrite_a_deliberate_flag(self, image):
        annotator = AnnotatorFactory()
        image.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=annotator,
            reason=StaffReviewFlagReason.SPECIES_ID,
        )
        self._skip_image_n_times(image, 3)

        assert auto_flag_for_staff(image) is True
        image.refresh_from_db()
        # The annotator's reason survives; it is more useful than "lots of skips"
        assert image.flag_source == StaffReviewFlagSource.MANUAL
        assert image.flag_reason == StaffReviewFlagReason.SPECIES_ID
        assert image.flagged_by == annotator


@pytest.mark.django_db
class TestFlagReasonDisplay:
    def test_blank_when_not_flagged(self, image):
        assert image.flag_reason_display == ""

    def test_shows_reason_label_for_manual_flag(self, image):
        image.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=AnnotatorFactory(),
            reason=StaffReviewFlagReason.BBOX_PROTOCOL,
        )

        assert image.flag_reason_display == "Bounding box protocol needs review"

    def test_appends_detail_for_other(self, image):
        image.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=AnnotatorFactory(),
            reason=StaffReviewFlagReason.OTHER,
            reason_detail="Lens obscured",
        )

        assert image.flag_reason_display == "Other: Lens obscured"

    def test_labels_auto_flagged_images(self, image):
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)

        assert image.flag_reason_display == "Auto-flagged"

    def test_handles_flags_predating_provenance(self, image):
        """Rows flagged before the provenance fields existed have no reason recorded."""
        Image.objects.filter(id=image.id).update(staff_review_needed=True)
        image.refresh_from_db()

        assert image.flag_reason_display == "Reason not recorded"


@pytest.mark.django_db
class TestCheckboxVisibility:
    """The checkbox was hidden from non-staff in #507; flagging is open again."""

    def test_volunteer_sees_the_flag_checkbox(self, client, user, image_with_bboxes):
        client.force_login(user)

        with patch("images.views.annotation.get_pil_image") as mock_pil:
            mock_pil.return_value = None
            response = client.get(reverse("images:annotate_species"))

        assert response.status_code == 200
        assert b"Flag for Staff Review" in response.content
        assert b"staff-review-reason" in response.content


@pytest.mark.django_db
class TestQueueReasonFilter:
    """The staff review queue can be narrowed to a single reason.

    Covers ``images.models.custom_fields.get_filter_params``, which feeds the annotation
    queues via ``set_view_filterset`` (the Search Images page builds its own Q() separately).
    """

    def test_reason_is_ignored_without_the_staff_review_flag(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, flag_reason=StaffReviewFlagReason.SPECIES_ID)

        # Filtering a normal queue by reason would be meaningless, so it is dropped
        assert "flag_reason" not in filters
        assert "staff_review_needed" not in filters

    def test_reason_narrows_a_staff_review_queue(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(
            None, None, None, None, staff_review_needed=True, flag_reason=StaffReviewFlagReason.BBOX_PROTOCOL
        )

        assert filters["staff_review_needed"] is True
        assert filters["flag_reason"] == StaffReviewFlagReason.BBOX_PROTOCOL

    def test_unrecognised_reason_is_dropped_rather_than_returning_nothing(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, staff_review_needed=True, flag_reason="nonsense")

        # A bad querystring value should widen to the whole queue, not silently empty it
        assert filters["staff_review_needed"] is True
        assert "flag_reason" not in filters

    def test_omitting_the_reason_leaves_the_queue_unfiltered(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, staff_review_needed=True)

        assert "flag_reason" not in filters

    def test_filters_apply_to_a_real_queryset(self):
        """The dict is splatted into Image.objects.filter(), so it must be valid lookups."""
        from images.models.custom_fields import get_filter_params

        wanted = ImageFactory()
        wanted.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=AnnotatorFactory(),
            reason=StaffReviewFlagReason.BBOX_PROTOCOL,
        )
        other = ImageFactory()
        other.flag_for_staff_review(
            source=StaffReviewFlagSource.MANUAL,
            annotator=AnnotatorFactory(),
            reason=StaffReviewFlagReason.SPECIES_ID,
        )
        auto = ImageFactory()
        auto.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)

        filters = get_filter_params(
            None, None, None, None, staff_review_needed=True, flag_reason=StaffReviewFlagReason.BBOX_PROTOCOL
        )
        results = list(Image.objects.filter(**filters))

        assert results == [wanted]
        assert other not in results
        assert auto not in results
