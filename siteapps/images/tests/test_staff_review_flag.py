# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Test suite for the "Flag for Staff Review" pipeline.

Covers ``images.views.annotation.annotation_processor`` flag handling,
``images.views.annotation.auto_flag_for_staff`` and the provenance helpers on
``images.models.Image``.

Behaviour these tests pin down:
- Manual flagging is disabled (Alys, Sept 2026): the checkbox is staff-only and greyed
  out, and an annotation submission never sets the flag, whatever it sends.
- A staff member saving annotations clears the flag, provenance included.
- Auto-flagging is recorded as such and never overwrites a flag someone asked for.
"""

import json
from unittest.mock import patch

import pytest
from conftest_factories import AnnotatorFactory, ImageFactory
from django.urls import reverse
from images.models import Image, StaffReviewFlagSource
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
class TestSubmittedFlagIsIgnored:
    """Manual flagging is off, so nothing an annotation submission sends can set the flag."""

    def test_a_submitted_flag_does_not_flag_the_image(self, client, user, image, fake_datastore):
        client.force_login(user)

        response = post_annotation(client, image, staff_review_needed="true")

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is False

    def test_a_volunteer_save_cannot_clear_an_existing_flag(self, client, user, fake_datastore):
        """The bug behind the whole thing: a page without the checkbox sent nothing, which was
        read as "not flagged", so any volunteer save silently emptied the review queue."""
        image = ImageFactory()
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)
        client.force_login(user)

        response = post_annotation(client, image, staff_review_needed="false")

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is True


@pytest.mark.django_db
class TestStaffSavingClearsTheFlag:
    def test_staff_saving_annotations_clears_the_flag(self, client, staff_user, fake_datastore):
        """Staff looking at the image is what the flag was asking for, so saving resolves it."""
        image = ImageFactory()
        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)
        client.force_login(staff_user)

        response = post_annotation(client, image)

        assert response.status_code == 200
        image.refresh_from_db()
        assert image.staff_review_needed is False
        # Provenance is cleared alongside the flag
        assert image.flag_source == ""
        assert image.flagged_at is None
        # ...and the review is recorded, so the skip threshold cannot re-flag it
        assert image.staff_reviewed_at is not None


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
        assert image.flagged_at is not None

    def test_auto_flag_does_not_overwrite_a_flag_someone_asked_for(self, image):
        """Nothing sets MANUAL now, but rows flagged while the checkbox was live still carry
        it, and "somebody asked" outranks "lots of skips"."""
        image.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL)
        self._skip_image_n_times(image, 3)

        assert auto_flag_for_staff(image) is True
        image.refresh_from_db()
        assert image.flag_source == StaffReviewFlagSource.MANUAL


@pytest.mark.django_db
class TestFlagReasonDisplay:
    def test_blank_when_not_flagged(self, image):
        assert image.flag_reason_display == ""

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
    """Alys asked for the checkbox to stay disabled, so the page must not offer it as a
    control: staff see it greyed out as a status light, volunteers do not see it at all."""

    def _annotate_page(self, client):
        with patch("images.views.annotation.get_pil_image") as mock_pil:
            mock_pil.return_value = None
            return client.get(reverse("images:annotate_species"))

    def test_a_volunteer_does_not_see_the_flag_checkbox(self, client, user, image_with_bboxes):
        client.force_login(user)

        response = self._annotate_page(client)

        assert response.status_code == 200
        assert b'id="staff-review-needed"' not in response.content

    def test_staff_see_it_greyed_out_rather_than_as_a_control(self, image):
        """Rendered directly: the annotate page only hands staff an image in the staff queue,
        and what matters here is the markup, not how they got to it."""
        from django.template.loader import render_to_string

        image.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)

        html = render_to_string(
            "images/annotate/page_elements/options.html",
            {"image": image, "user": type("U", (), {"is_staff": True, "is_authenticated": True})()},
        )

        assert 'id="staff-review-needed"' in html
        assert "disabled" in html
        # The reason picker went with the manual flow
        assert "staff-review-reason" not in html
        # Staff can still see why it is in their queue
        assert "Auto-flagged" in html


@pytest.mark.django_db
class TestQueueSourceFilter:
    """The staff review queue can be narrowed to one kind of flag.

    Covers ``images.models.custom_fields.get_filter_params``, which feeds the annotation
    queues via ``set_view_filterset`` (the Search Images page builds its own Q() separately).
    """

    def test_source_is_ignored_without_the_staff_review_flag(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, flag_source=StaffReviewFlagSource.AUTO_SKIPS)

        # Filtering a normal queue by flag source would be meaningless, so it is dropped
        assert "flag_source" not in filters
        assert "staff_review_needed" not in filters

    def test_source_narrows_a_staff_review_queue(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(
            None, None, None, None, staff_review_needed=True, flag_source=StaffReviewFlagSource.AUTO_SKIPS
        )

        assert filters["staff_review_needed"] is True
        assert filters["flag_source"] == StaffReviewFlagSource.AUTO_SKIPS

    def test_asking_for_deliberate_flags_includes_the_ones_predating_provenance(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(
            None, None, None, None, staff_review_needed=True, flag_source=StaffReviewFlagSource.MANUAL
        )

        # A blank source is more likely somebody's request than an auto-flag, so it counts
        assert filters["flag_source__in"] == [StaffReviewFlagSource.MANUAL, ""]

    def test_unrecognised_source_is_dropped_rather_than_returning_nothing(self):
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, staff_review_needed=True, flag_source="nonsense")

        # A bad querystring value should widen to the whole queue, not silently empty it
        assert filters["staff_review_needed"] is True
        assert "flag_source" not in filters

    def test_omitting_the_source_leaves_the_queue_unfiltered(self):
        """What the review queue does by default now: every flagged image, however it got
        there, since the automatic threshold is the only thing still raising flags."""
        from images.models.custom_fields import get_filter_params

        filters = get_filter_params(None, None, None, None, staff_review_needed=True)

        assert "flag_source" not in filters
        assert "flag_source__in" not in filters

    def test_filters_apply_to_a_real_queryset(self):
        """The dict is splatted into Image.objects.filter(), so it must be valid lookups."""
        from images.models.custom_fields import get_filter_params

        wanted = ImageFactory()
        wanted.flag_for_staff_review(source=StaffReviewFlagSource.AUTO_SKIPS)
        earlier = ImageFactory()
        earlier.flag_for_staff_review(source=StaffReviewFlagSource.MANUAL)

        filters = get_filter_params(
            None, None, None, None, staff_review_needed=True, flag_source=StaffReviewFlagSource.AUTO_SKIPS
        )
        results = list(Image.objects.filter(**filters))

        assert results == [wanted]
        assert earlier not in results
