# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the auto_approve_single_human backlog management command."""

import pytest
from django.core.management import call_command

from images.models import Image
from images.processors.annotation import SERVICE_ACCOUNT_EMAIL, get_service_annotator
from siteapps.conftest_factories import BoundingBoxFactory, CategoryFactory, ImageFactory


def _make_single_human_image(confidence: float) -> Image:
    """Create a processed image with exactly one person bounding box at the given confidence."""
    image = ImageFactory(processed=True)
    bbox = BoundingBoxFactory(image=image, confidence=confidence)
    CategoryFactory(bounding_box=bbox, name="person")
    return image


@pytest.mark.django_db
def test_approves_high_confidence_single_human():
    """A single person bbox above the cutoff is completed for category and species pipelines."""
    image = _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85")

    image.refresh_from_db()
    assert image.category_pipeline_complete is True
    assert image.species_pipeline_complete is True
    assert image.has_uncertain_bbox is False


@pytest.mark.django_db
def test_records_service_account_vote():
    """The approval is attributable: the service account holds an accept vote on the category."""
    image = _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85")

    service_annotator = get_service_annotator()
    assert service_annotator.human.email == SERVICE_ACCOUNT_EMAIL
    category = image.boundingbox_set.first().category_set.first()
    assert service_annotator in category.accepted_by.all()


@pytest.mark.django_db
def test_skips_below_confidence():
    """A person bbox below the cutoff is left untouched."""
    image = _make_single_human_image(confidence=0.80)

    call_command("auto_approve_single_human", "--confidence", "0.85")

    image.refresh_from_db()
    assert image.category_pipeline_complete is False
    assert image.species_pipeline_complete is False


@pytest.mark.django_db
def test_skips_multiple_boxes():
    """An image with more than one bounding box does not qualify."""
    image = _make_single_human_image(confidence=0.95)
    extra = BoundingBoxFactory(image=image, confidence=0.95)
    CategoryFactory(bounding_box=extra, name="animal")

    call_command("auto_approve_single_human", "--confidence", "0.85")

    image.refresh_from_db()
    assert image.species_pipeline_complete is False


@pytest.mark.django_db
def test_skips_non_person():
    """A single high-confidence animal box does not qualify."""
    image = ImageFactory(processed=True)
    bbox = BoundingBoxFactory(image=image, confidence=0.95)
    CategoryFactory(bounding_box=bbox, name="animal")

    call_command("auto_approve_single_human", "--confidence", "0.85")

    image.refresh_from_db()
    assert image.species_pipeline_complete is False


@pytest.mark.django_db
def test_dry_run_makes_no_changes():
    """--dry-run reports qualifying images without modifying them."""
    image = _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85", "--dry-run")

    image.refresh_from_db()
    assert image.species_pipeline_complete is False


@pytest.mark.django_db
def test_limit_caps_approvals():
    """--limit approves at most the requested number of images."""
    images = [_make_single_human_image(confidence=0.95) for _ in range(3)]

    call_command("auto_approve_single_human", "--confidence", "0.85", "--limit", "1")

    completed = [img for img in images if Image.objects.get(id=img.id).species_pipeline_complete]
    assert len(completed) == 1


@pytest.mark.django_db
def test_idempotent_rerun():
    """A second run approves no additional images (already-voted images are skipped)."""
    _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85")
    # A re-run must not raise and must leave the completed image completed.
    call_command("auto_approve_single_human", "--confidence", "0.85")

    assert Image.objects.filter(species_pipeline_complete=True).count() == 1
