# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the auto_approve_single_human backlog management command."""

from datetime import datetime
from io import StringIO
from unittest.mock import patch
from uuid import UUID

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from images.management.commands.auto_approve_single_human import Command
from images.models import Annotator, Bot, BoundingBox, Category, Image
from images.processors.annotation import SINGLE_HUMAN_RULE, get_automation_annotator

from siteapps.conftest_factories import AnnotatorFactory, BoundingBoxFactory, CategoryFactory, ImageFactory


def _make_single_human_image(confidence: float, **image_kwargs) -> Image:
    """Create a processed image with one person box and optional image attributes."""
    image = ImageFactory(processed=True, **image_kwargs)
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
def test_records_automation_bot_vote():
    """The approval is attributable: the automation bot holds an accept vote on the category."""
    image = _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85")

    automation_annotator = get_automation_annotator()
    assert automation_annotator.type == "bot"
    assert automation_annotator.automation_criteria == SINGLE_HUMAN_RULE
    category = image.boundingbox_set.first().category_set.first()
    assert automation_annotator in category.accepted_by.all()


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
    """--dry-run reports qualifying images without modifying data or provisioning its bot."""
    image = _make_single_human_image(confidence=0.95)
    initial_bot_count = Bot.objects.count()
    initial_annotator_count = Annotator.objects.count()

    call_command("auto_approve_single_human", "--confidence", "0.85", "--dry-run")

    image.refresh_from_db()
    assert image.species_pipeline_complete is False
    assert Bot.objects.count() == initial_bot_count
    assert Annotator.objects.count() == initial_annotator_count


@pytest.mark.django_db
def test_limit_caps_approvals():
    """--limit approves at most the requested number of images."""
    images = [_make_single_human_image(confidence=0.95) for _ in range(3)]

    call_command("auto_approve_single_human", "--confidence", "0.85", "--limit", "1")

    completed = [img for img in images if Image.objects.get(id=img.id).species_pipeline_complete]
    assert len(completed) == 1


@pytest.mark.django_db
def test_limit_is_applied_inside_candidate_count_query():
    """A limited run must not count the entire eligible backlog before processing."""
    for _ in range(3):
        _make_single_human_image(confidence=0.95)
    stdout = StringIO()

    call_command("auto_approve_single_human", "--dry-run", "--limit", "1", "--timing", stdout=stdout)

    output = stdout.getvalue()
    assert "section=candidate_count" in output
    assert "candidates=1" in output
    assert "mode=limited" in output


@pytest.mark.django_db
def test_idempotent_rerun():
    """A second run approves no additional images (already-voted images are skipped)."""
    _make_single_human_image(confidence=0.95)

    call_command("auto_approve_single_human", "--confidence", "0.85")
    # A re-run must not raise and must leave the completed image completed.
    call_command("auto_approve_single_human", "--confidence", "0.85")

    assert Image.objects.filter(species_pipeline_complete=True).count() == 1


@pytest.mark.django_db
def test_date_range_includes_both_boundary_dates():
    """Start and end dates include every capture time on both boundary dates."""
    before = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=timezone.make_aware(datetime(2025, 1, 9, 23, 59)),
    )
    start = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=timezone.make_aware(datetime(2025, 1, 10, 0, 0)),
    )
    end = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=timezone.make_aware(datetime(2025, 1, 20, 23, 59)),
    )
    after = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=timezone.make_aware(datetime(2025, 1, 21, 0, 0)),
    )

    call_command(
        "auto_approve_single_human",
        "--start-date",
        "2025-01-10",
        "--end-date",
        "2025-01-20",
    )

    assert Image.objects.get(id=start.id).species_pipeline_complete is True
    assert Image.objects.get(id=end.id).species_pipeline_complete is True
    assert Image.objects.get(id=before.id).species_pipeline_complete is False
    assert Image.objects.get(id=after.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_camera_station_filter_is_exact():
    """Only an exact camera station ID match is approved."""
    matching = _make_single_human_image(
        confidence=0.95,
        upload__camera_station__station_id="TEST-STATION",
    )
    partial = _make_single_human_image(
        confidence=0.95,
        upload__camera_station__station_id="TEST-STATION-OTHER",
    )

    call_command("auto_approve_single_human", "--camera-station", "TEST-STATION")

    assert Image.objects.get(id=matching.id).species_pipeline_complete is True
    assert Image.objects.get(id=partial.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_macro_site_filter_is_exact():
    """Only images belonging to the exact macro-site name are approved."""
    matching = _make_single_human_image(
        confidence=0.95,
        upload__camera_station__micro_site__macro_site__name="Test Macro",
    )
    partial = _make_single_human_image(
        confidence=0.95,
        upload__camera_station__micro_site__macro_site__name="Test Macro Other",
    )

    call_command("auto_approve_single_human", "--macro-site", "Test Macro")

    assert Image.objects.get(id=matching.id).species_pipeline_complete is True
    assert Image.objects.get(id=partial.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_scope_filters_can_be_combined():
    """An image must satisfy every supplied date and location filter."""
    captured = timezone.make_aware(datetime(2025, 2, 15, 12, 0))
    matching = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=captured,
        upload__camera_station__station_id="COMBINED-STATION",
        upload__camera_station__micro_site__macro_site__name="Combined Macro",
    )
    wrong_station = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=captured,
        upload__camera_station__station_id="OTHER-STATION",
        upload__camera_station__micro_site__macro_site__name="Combined Macro",
    )

    call_command(
        "auto_approve_single_human",
        "--start-date",
        "2025-02-01",
        "--end-date",
        "2025-02-28",
        "--camera-station",
        "COMBINED-STATION",
        "--macro-site",
        "Combined Macro",
    )

    assert Image.objects.get(id=matching.id).species_pipeline_complete is True
    assert Image.objects.get(id=wrong_station.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_invalid_date_is_rejected():
    """A malformed date fails before backlog images are changed."""
    image = _make_single_human_image(confidence=0.95)

    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command("auto_approve_single_human", "--start-date", "01/10/2025")

    assert Image.objects.get(id=image.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_inverted_date_range_is_rejected():
    """The start date cannot occur after the end date."""
    with pytest.raises(CommandError, match="on or before"):
        call_command(
            "auto_approve_single_human",
            "--start-date",
            "2025-02-01",
            "--end-date",
            "2025-01-01",
        )


@pytest.mark.django_db
def test_dry_run_output_describes_active_scope():
    """Dry-run output identifies the exact test scope without modifying images."""
    image = _make_single_human_image(
        confidence=0.95,
        trigger_timestamp=timezone.make_aware(datetime(2025, 3, 5, 12, 0)),
        upload__camera_station__station_id="OUTPUT-STATION",
        upload__camera_station__micro_site__macro_site__name="Output Macro",
    )
    stdout = StringIO()

    call_command(
        "auto_approve_single_human",
        "--dry-run",
        "--start-date",
        "2025-03-01",
        "--end-date",
        "2025-03-31",
        "--camera-station",
        "OUTPUT-STATION",
        "--macro-site",
        "Output Macro",
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert "start_date=2025-03-01" in output
    assert "end_date=2025-03-31" in output
    assert "camera_station=OUTPUT-STATION" in output
    assert "macro_site=Output Macro" in output
    assert Image.objects.get(id=image.id).species_pipeline_complete is False


@pytest.mark.django_db
def test_timing_flag_prints_section_diagnostics():
    """Opt-in diagnostics identify candidate, batch, and total command timings."""
    _make_single_human_image(confidence=0.95)
    stdout = StringIO()

    call_command("auto_approve_single_human", "--timing", stdout=stdout)

    output = stdout.getvalue()
    assert "[timing] section=candidate_count" in output
    assert "[timing] section=batch_load" in output
    assert "[timing] section=batch_votes" in output
    assert "[timing] section=batch_state_updates" in output
    assert "[timing] section=batch_transaction" in output
    assert "[timing] section=command_total" in output


@pytest.mark.django_db
def test_non_default_confidence_is_used_during_approval():
    """The shared approval routine honors the command's non-default confidence cutoff."""
    image = _make_single_human_image(confidence=0.80)

    call_command("auto_approve_single_human", "--confidence", "0.75")

    assert Image.objects.get(id=image.id).species_pipeline_complete is True


@pytest.mark.django_db
def test_bulk_fast_path_removes_contradictory_automation_rejects():
    """Bulk acceptance preserves vote() semantics by removing prior reject votes."""
    image = _make_single_human_image(confidence=0.95)
    bbox = image.boundingbox_set.get()
    category = bbox.category_set.get()
    automation_annotator = get_automation_annotator()
    bbox.rejected_by.add(automation_annotator)
    category.rejected_by.add(automation_annotator)

    call_command("auto_approve_single_human", "--confidence", "0.85")

    assert bbox.accepted_by.filter(id=automation_annotator.id).exists()
    assert category.accepted_by.filter(id=automation_annotator.id).exists()
    assert not bbox.rejected_by.filter(id=automation_annotator.id).exists()
    assert not category.rejected_by.filter(id=automation_annotator.id).exists()


@pytest.mark.django_db
def test_unusual_extra_category_uses_existing_fallback_behavior():
    """A legacy multi-category box is handled by the general per-image validity cascade."""
    image = _make_single_human_image(confidence=0.95)
    bbox = image.boundingbox_set.get()
    CategoryFactory(bounding_box=bbox, name="animal")

    call_command("auto_approve_single_human", "--confidence", "0.85")

    image.refresh_from_db()
    person = bbox.category_set.get(name="person")
    automation_annotator = get_automation_annotator()
    assert person.accepted_by.filter(id=automation_annotator.id).exists()
    assert image.species_pipeline_complete is True
    assert image.category_pipeline_complete is False


@pytest.mark.django_db
def test_bulk_work_has_near_constant_query_count_within_one_batch():
    """Adding images to one batch must not restore per-image query growth."""
    get_automation_annotator()
    _make_single_human_image(confidence=0.95)
    with CaptureQueriesContext(connection) as single_queries:
        call_command("auto_approve_single_human", "--confidence", "0.85", "--batch-size", "100")

    for _ in range(25):
        _make_single_human_image(confidence=0.95)
    with CaptureQueriesContext(connection) as batch_queries:
        call_command("auto_approve_single_human", "--confidence", "0.85", "--batch-size", "100")

    # A few extra statements are allowed for backend-specific bulk-insert chunking. The old
    # implementation added roughly 25-35 statements for every additional image.
    assert len(batch_queries) <= len(single_queries) + 8


class _FakeCandidatePage:
    """Minimal queryset-shaped object for exercising million-scale paging orchestration."""

    def __init__(self, image_ids):
        self.image_ids = image_ids
        self.iterator_calls = 0

    def count(self):
        return len(self.image_ids)

    def filter(self, *, image_id__gt):
        return _FakeCandidatePage([image_id for image_id in self.image_ids if image_id > image_id__gt])

    def values_list(self, *args, **kwargs):
        return self

    def iterator(self, *, chunk_size):
        self.iterator_calls += 1
        return iter(self.image_ids)

    def __getitem__(self, item):
        return self.image_ids[item]


@pytest.mark.django_db
def test_pages_more_than_two_thousand_candidates_without_materializing_backlog():
    """The command visits 5,001 candidates as 2,000/2,000/1,001 pages."""
    image_ids = [UUID(int=value) for value in range(1, 5002)]
    candidates = _FakeCandidatePage(image_ids)
    batch_lengths = []

    def approve_batch(_command, batch, **kwargs):
        batch_lengths.append(len(batch))
        return len(batch), 0

    with (
        patch.object(Command, "_get_qualifying_image_ids", return_value=candidates),
        patch.object(Command, "_approve_batch", autospec=True, side_effect=approve_batch),
        patch(
            "images.management.commands.auto_approve_single_human.get_automation_annotator",
            return_value=object(),
        ),
    ):
        call_command("auto_approve_single_human", "--batch-size", "2000")

    assert batch_lengths == [2000, 2000, 1001]
    assert candidates.iterator_calls == 1


@pytest.mark.django_db(transaction=True)
def test_bulk_approval_crosses_multiple_real_database_batches():
    """Approve 10,001 real candidates across six batches using bulk-built fixtures."""
    image_count = 10001
    upload = ImageFactory().upload
    creator = AnnotatorFactory(bot_annotator=True)
    images = [
        Image(
            upload=upload,
            dropbox_file_name=f"bulk-{index}.jpg",
            dropbox_file_path=f"/bulk/{index}.jpg",
            dropbox_file_path_display=f"/bulk/{index}.jpg",
            dropbox_content_hash=f"{index:064x}",
            dropbox_file_id=f"bulk:{index}",
            file_size=1,
            processed=True,
        )
        for index in range(image_count)
    ]
    Image.objects.bulk_create(images, batch_size=1000)
    boxes = [
        BoundingBox(
            image=image,
            x=0.1,
            y=0.1,
            w=0.2,
            h=0.2,
            confidence=0.95,
            created_by=creator,
        )
        for image in images
    ]
    BoundingBox.objects.bulk_create(boxes, batch_size=1000)
    categories = [
        Category(
            bounding_box=box,
            name="person",
            confidence=0.95,
            created_by=creator,
        )
        for box in boxes
    ]
    Category.objects.bulk_create(categories, batch_size=1000)

    call_command("auto_approve_single_human", "--confidence", "0.85", "--batch-size", "2000")

    approved_images = Image.objects.filter(id__in=[image.id for image in images])
    assert approved_images.filter(category_pipeline_complete=True).count() == image_count
    assert approved_images.filter(species_pipeline_complete=True).count() == image_count
    automation_annotator = get_automation_annotator()
    assert BoundingBox.accepted_by.through.objects.filter(annotator_id=automation_annotator.id).count() == image_count
    assert Category.accepted_by.through.objects.filter(annotator_id=automation_annotator.id).count() == image_count


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--batch-size", "0", "greater than zero"),
        ("--limit", "-1", "zero or greater"),
    ],
)
def test_rejects_invalid_batch_controls(option, value, message):
    """Invalid controls fail before candidate discovery or database writes."""
    with pytest.raises(CommandError, match=message):
        call_command("auto_approve_single_human", option, value)
