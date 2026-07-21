# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the single-human auto-approval routine, queue exclusion, and forward-path wiring.

Covers ``images.processors.annotation.auto_approve_single_human`` (the shared routine), its
effect on the species and human-behavior queue queries, and its invocation from
``images.processors.image.process_image`` at upload time.
"""

from unittest.mock import patch

import pytest

from images.models import Image
from images.processors.annotation import (
    PERSON_CATEGORY,
    SERVICE_ACCOUNT_EMAIL,
    auto_approve_single_human,
    get_service_annotator,
)
from images.views.annotation import (
    CATEGORY_ANIMAL,
    CATEGORY_HUMAN,
    activity_pipeline_query,
    species_pipeline_query,
)
from siteapps.conftest_factories import (
    AnnotatorFactory,
    BoundingBoxFactory,
    CategoryFactory,
    ImageFactory,
)

CONFIDENCE_ABOVE = 0.95
CONFIDENCE_BELOW = 0.50


def _single_human_image(confidence: float = CONFIDENCE_ABOVE, **image_kwargs) -> Image:
    """Create a processed image with exactly one person bounding box.

    Args:
        confidence: Confidence of the single person bounding box.
        **image_kwargs: Extra fields forwarded to ``ImageFactory`` (e.g. queue-relevant flags).

    Returns:
        The saved ``Image``.
    """
    image = ImageFactory(processed=True, **image_kwargs)
    bbox = BoundingBoxFactory(image=image, confidence=confidence)
    CategoryFactory(bounding_box=bbox, name=PERSON_CATEGORY)
    return image


@pytest.mark.django_db
class TestAutoApproveSingleHumanRoutine:
    """Unit tests for the shared ``auto_approve_single_human`` routine."""

    def test_qualifying_image_is_approved(self):
        """A single high-confidence person box completes category and species pipelines."""
        image = _single_human_image()

        approved = auto_approve_single_human(image)

        image.refresh_from_db()
        assert approved is True
        assert image.category_pipeline_complete is True
        assert image.species_pipeline_complete is True
        assert image.has_humans is True
        assert image.has_animals is False
        assert image.has_uncertain_bbox is False

    def test_approval_records_service_account_vote(self):
        """The person category carries the expert service-account accept vote (audit trail)."""
        image = _single_human_image()

        auto_approve_single_human(image)

        service_annotator = get_service_annotator()
        assert service_annotator.human.email == SERVICE_ACCOUNT_EMAIL
        category = image.boundingbox_set.first().category_set.first()
        assert service_annotator in category.accepted_by.all()

    def test_below_confidence_is_not_approved(self):
        """A person box below the cutoff does not qualify."""
        image = _single_human_image(confidence=CONFIDENCE_BELOW)

        approved = auto_approve_single_human(image)

        image.refresh_from_db()
        assert approved is False
        assert image.category_pipeline_complete is False
        assert image.species_pipeline_complete is False

    def test_multiple_boxes_is_not_approved(self):
        """An image with more than one bounding box does not qualify."""
        image = _single_human_image()
        extra = BoundingBoxFactory(image=image, confidence=CONFIDENCE_ABOVE)
        CategoryFactory(bounding_box=extra, name="animal")

        approved = auto_approve_single_human(image)

        image.refresh_from_db()
        assert approved is False
        assert image.species_pipeline_complete is False

    def test_non_person_box_is_not_approved(self):
        """A single high-confidence animal box does not qualify."""
        image = ImageFactory(processed=True)
        bbox = BoundingBoxFactory(image=image, confidence=CONFIDENCE_ABOVE)
        CategoryFactory(bounding_box=bbox, name="animal")

        approved = auto_approve_single_human(image)

        image.refresh_from_db()
        assert approved is False
        assert image.species_pipeline_complete is False


@pytest.mark.django_db
class TestAutoApprovedImageExcludedFromQueues:
    """An auto-approved single-human image must leave both queues it would otherwise sit in."""

    def _queue_eligible_single_human_image(self) -> Image:
        """Create a single-human image with the flags that make it a queue candidate pre-approval.

        The species and activity queries require ``use_precomputed_flags=True``; the species query
        also requires ``has_bbox_above_confidence_threshold=True`` and (pre-approval) an uncertain
        box. Returns the image before ``auto_approve_single_human`` has run.

        Returns:
            The queue-eligible single-human ``Image``.
        """
        return _single_human_image(
            use_precomputed_flags=True,
            has_bbox_above_confidence_threshold=True,
            has_uncertain_bbox=True,
        )

    def test_excluded_from_species_queue_after_approval(self):
        """After approval, the image no longer satisfies the species queue query."""
        image = self._queue_eligible_single_human_image()
        annotator = AnnotatorFactory()

        # Pre-approval: the uncertain box places it in the species queue.
        pre = species_pipeline_query(Image.objects.all(), annotator)
        assert image in pre

        auto_approve_single_human(image)

        post = species_pipeline_query(Image.objects.all(), annotator)
        assert image not in post

    def test_excluded_from_human_behavior_queue_after_approval(self):
        """After approval, the image is excluded from the human-behavior queue by service vote."""
        image = self._queue_eligible_single_human_image()
        annotator = AnnotatorFactory()

        auto_approve_single_human(image)

        # has_humans=True now, but the service-account vote marker excludes it.
        queue = activity_pipeline_query(Image.objects.all(), annotator, CATEGORY_HUMAN)
        assert image not in queue

    def test_absent_from_animal_queue_after_approval(self):
        """The human-only image never belongs in the animal queue (has_wild_animals=False)."""
        image = self._queue_eligible_single_human_image()
        annotator = AnnotatorFactory()

        auto_approve_single_human(image)

        queue = activity_pipeline_query(Image.objects.all(), annotator, CATEGORY_ANIMAL)
        assert image not in queue


@pytest.mark.django_db
class TestForwardPathInvokesAutoApproval:
    """``process_image`` must invoke ``auto_approve_single_human`` at upload time."""

    @patch("images.processors.image.auto_approve_single_human")
    @patch("images.processors.image.run_model_inference")
    def test_process_image_calls_auto_approve(self, mock_inference, mock_auto_approve):
        """After inference and processed=True, the auto-approval routine runs on the image."""
        from images.processors.image import process_image

        # A thumbnail already present skips the Dropbox thumbnail fetch; a truthy
        # species_ai_detections skips the species inference call and the "Puma" membership test.
        image = ImageFactory(
            processed=False,
            thumbnail_gcloud_path="thumbnails/1024/test.jpg",
            species_ai_detections="none",
        )

        process_image(image, dbx=object())

        mock_inference.assert_called_once_with(image)
        mock_auto_approve.assert_called_once_with(image)
        assert image.processed is True
