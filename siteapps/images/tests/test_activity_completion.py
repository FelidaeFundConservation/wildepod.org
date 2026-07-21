# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""tests for human-only images completing the activity pipeline.

Target coverage: ``images.views.annotation.calculateActivityAnnotationFlags``.

A human-only image (``has_humans=True``, ``has_wild_animals=False``) must be able to complete
the activity pipeline once it has a valid, voted human-behavior annotation. Previously the
completion gate required ``has_wild_animals=True``, so these images looped in the human-behavior
queue forever. The gate now accepts either subject type
(``image.has_wild_animals or image.has_humans``).
"""

import pytest
from django.contrib.auth import get_user_model

from images.models import Image
from images.views.annotation import (
    CATEGORY_ANIMAL,
    CATEGORY_HUMAN,
    activity_pipeline_query,
    calculateActivityAnnotationFlags,
)
from siteapps.conftest_factories import (
    ActivityFactory,
    ActivityTypeFactory,
    AnnotatorFactory,
    BoundingBoxFactory,
    ImageFactory,
)

User = get_user_model()


def _expert_annotator():
    """Create and return a human ``Annotator`` backed by an expert user.

    Creating an annotation as an expert counts as a staff/expert vote, which makes the
    annotation VALID on its own.

    Returns:
        The expert human ``Annotator``.
    """
    expert = User.objects.create_user(email="behavior-expert@example.com", password="testpass123")
    expert.is_expert = True
    expert.save()
    return AnnotatorFactory(human=expert)


def _add_valid_activity(image, category, annotator, type_name):
    """Add one bounding box with a valid, expert-voted activity to an image.

    Because ``annotator`` is an expert, the created activity is VALID (its creation counts as a
    staff/expert vote), so it contributes a valid — not uncertain — activity annotation.

    Args:
        image: The ``Image`` to attach the bounding box to.
        category: The ``ActivityType`` category label (e.g. ``"animal"`` or ``"human"``).
        annotator: The expert ``Annotator`` creating the box and activity.
        type_name: Unique ``ActivityType`` name (must be distinct per get-or-create).

    Returns:
        The created ``Activity``.
    """
    bbox = BoundingBoxFactory(image=image, created_by=annotator)
    activity_type = ActivityTypeFactory(name=type_name, category=category)
    return ActivityFactory(bounding_box=bbox, name=activity_type, created_by=annotator)


@pytest.mark.django_db
class TestHumanActivityCompletion:
    """Human-only images must be able to complete the shared activity-completion gate."""

    def _human_only_image(self):
        """Create and return a processed, human-only image.

        Returns:
            The saved ``Image`` with ``processed``/``has_humans`` set and
            ``has_wild_animals`` cleared.
        """
        return ImageFactory(processed=True, has_humans=True, has_wild_animals=False)

    def test_human_only_image_completes_activity_via_expert_vote(self):
        """An expert-created human-behavior annotation completes the pipeline for a human image."""
        image = self._human_only_image()

        expert = _expert_annotator()
        bbox = BoundingBoxFactory(image=image, created_by=expert)
        activity_type = ActivityTypeFactory(name="Walking", category="human")
        ActivityFactory(bounding_box=bbox, name=activity_type, created_by=expert)

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"] is True
        assert image.activity_pipeline_complete is True

    def test_human_only_image_without_annotation_stays_incomplete(self):
        """A human-only image with no valid behavior annotation must remain incomplete."""
        image = self._human_only_image()
        BoundingBoxFactory(image=image)

        calculateActivityAnnotationFlags(image)
        image.save()

        assert image.activity_pipeline_complete is False


@pytest.mark.django_db
class TestActivityCompletionBySubjectComposition:
    """The activity gate completes for animal, multi-animal, and mixed human/animal images.

    All three carry ``has_wild_animals=True`` (they contain at least one wild animal), so they
    satisfy the gate's subject condition. Each test gives every bounding box a valid, expert-voted
    activity so the image has a valid — and no uncertain — activity annotation.
    """

    def test_single_animal_image_completes(self):
        """One wild-animal box with a valid activity completes the pipeline."""
        image = ImageFactory(processed=True, has_wild_animals=True, has_humans=False)
        expert = _expert_annotator()

        _add_valid_activity(image, "animal", expert, "Grazing")

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["activity_has_uncertain"] is False
        assert image.activity_pipeline_complete is True

    def test_two_animal_image_completes(self):
        """Two wild-animal boxes, each with a valid activity, complete the pipeline."""
        image = ImageFactory(processed=True, has_wild_animals=True, has_humans=False)
        expert = _expert_annotator()

        _add_valid_activity(image, "animal", expert, "Grazing")
        _add_valid_activity(image, "animal", expert, "Running")

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["activity_has_uncertain"] is False
        assert image.activity_pipeline_complete is True

    def test_mixed_human_and_animal_image_completes(self):
        """A mixed image (one human box, one wild-animal box) completes the pipeline."""
        image = ImageFactory(processed=True, has_wild_animals=True, has_humans=True)
        expert = _expert_annotator()

        _add_valid_activity(image, "human", expert, "Walking")
        _add_valid_activity(image, "animal", expert, "Grazing")

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["activity_has_uncertain"] is False
        assert image.activity_pipeline_complete is True

    def test_mixed_human_and_vehicle_image_completes(self):
        """A human+vehicle image completes via the human box's valid activity.

        The vehicle box carries no activity annotation (vehicles have no behavior); completion is
        driven by the human box, and the image qualifies on ``has_humans=True``.
        """
        image = ImageFactory(processed=True, has_humans=True, has_vehicles=True, has_wild_animals=False)
        expert = _expert_annotator()

        _add_valid_activity(image, "human", expert, "Walking")
        # Vehicle box with no activity — present but not behavior-annotated.
        BoundingBoxFactory(image=image, created_by=expert)

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["activity_has_uncertain"] is False
        assert image.activity_pipeline_complete is True

    def test_mixed_animal_and_vehicle_image_completes(self):
        """An animal+vehicle image completes via the animal box's valid activity.

        The vehicle box carries no activity annotation; completion is driven by the wild-animal
        box, and the image qualifies on ``has_wild_animals=True``.
        """
        image = ImageFactory(processed=True, has_wild_animals=True, has_vehicles=True, has_humans=False)
        expert = _expert_annotator()

        _add_valid_activity(image, "animal", expert, "Grazing")
        # Vehicle box with no activity — present but not behavior-annotated.
        BoundingBoxFactory(image=image, created_by=expert)

        debug_info = calculateActivityAnnotationFlags(image)
        image.save()

        assert debug_info["flag_checks"]["activity_has_valid"] is True
        assert debug_info["flag_checks"]["activity_has_uncertain"] is False
        assert image.activity_pipeline_complete is True


@pytest.mark.django_db
class TestVehicleImageExcludedFromActivityQueues:
    """A vehicle-only image must be served by neither activity queue.

    ``activity_pipeline_query`` filters the human queue on ``has_humans=True`` and the animal
    queue on ``has_wild_animals=True``. A vehicle-only image has both flags ``False`` (there is no
    behavior to annotate for a vehicle), so it should appear in neither queue.
    """

    def _vehicle_only_image(self):
        """Create a processed vehicle-only image eligible for the queue filters.

        ``use_precomputed_flags`` must be ``True`` for the image to pass ``activity_pipeline_query``.

        Returns:
            The saved vehicle-only ``Image``.
        """
        return ImageFactory(
            processed=True,
            use_precomputed_flags=True,
            has_vehicles=True,
            has_humans=False,
            has_wild_animals=False,
        )

    def test_vehicle_only_image_absent_from_human_queue(self):
        """A vehicle-only image is not served by the human activity queue."""
        image = self._vehicle_only_image()
        annotator = _expert_annotator()

        queue = activity_pipeline_query(Image.objects.all(), annotator, CATEGORY_HUMAN)

        assert image not in queue

    def test_vehicle_only_image_absent_from_animal_queue(self):
        """A vehicle-only image is not served by the animal activity queue."""
        image = self._vehicle_only_image()
        annotator = _expert_annotator()

        queue = activity_pipeline_query(Image.objects.all(), annotator, CATEGORY_ANIMAL)

        assert image not in queue
