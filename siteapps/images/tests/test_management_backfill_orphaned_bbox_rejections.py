# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the backfill_orphaned_bbox_rejections management command.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from images.models import Annotator, BoundingBox, Category
from images.processors.annotation import vote
from images.views.annotation import calculateCategoryAnnotationFlags

User = get_user_model()


@pytest.fixture
def creator(user):
    annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
    return annotator


@pytest.mark.django_db
class TestBackfillOrphanedBboxRejections:
    def _make_stuck_image(self, image, creator):
        """
        Reproduce the pre-fix bug directly: reject a bbox (M2M only, the way
        the old handle_bbox_deletions() behaved) without ever voting on its
        Category child, leaving it orphaned at UNCERTAIN forever.
        """
        image.processed = True
        image.save()

        good_bbox = BoundingBox.objects.create(image=image, x=0.1, y=0.1, w=0.3, h=0.3, created_by=creator)
        good_category = Category.objects.create(bounding_box=good_bbox, name="vehicle", created_by=creator)
        accepter_user = User.objects.create_user(email="accepter@test.com", password="pass")
        accepter, _ = Annotator.objects.get_or_create(type="human", human=accepter_user)
        vote(good_category, accepter, accept=True)

        bad_bbox = BoundingBox.objects.create(image=image, x=0.6, y=0.6, w=0.2, h=0.2, created_by=creator)
        bad_category = Category.objects.create(bounding_box=bad_bbox, name="vehicle", created_by=creator)

        for i in range(3):
            rejecter_user = User.objects.create_user(email=f"rejecter{i}@test.com", password="pass")
            rejecter, _ = Annotator.objects.get_or_create(type="human", human=rejecter_user)
            vote(bad_bbox, rejecter, accept=False)  # bbox-only vote, mirrors pre-fix behavior

        calculateCategoryAnnotationFlags(image)
        image.save()

        assert image.category_pipeline_complete is False
        return bad_bbox, bad_category

    def test_dry_run_reports_but_does_not_write(self, image, creator):
        bad_bbox, bad_category = self._make_stuck_image(image, creator)

        call_command("backfill_orphaned_bbox_rejections", "--dry-run", "--image-id", str(image.id))

        bad_category.refresh_from_db()
        image.refresh_from_db()
        assert bad_category.rejected_by.count() == 0
        assert image.category_pipeline_complete is False

    def test_sweep_fixes_stuck_image(self, image, creator):
        bad_bbox, bad_category = self._make_stuck_image(image, creator)

        call_command("backfill_orphaned_bbox_rejections", "--image-id", str(image.id))

        bad_category.refresh_from_db()
        bad_bbox.refresh_from_db()
        image.refresh_from_db()
        assert bad_category.rejected_by.count() == 3
        assert bad_category.validity == "INVALID"
        assert bad_bbox.validity == "INVALID"
        assert image.category_pipeline_complete is True

    def test_sweep_is_idempotent(self, image, creator):
        bad_bbox, bad_category = self._make_stuck_image(image, creator)

        call_command("backfill_orphaned_bbox_rejections", "--image-id", str(image.id))
        call_command("backfill_orphaned_bbox_rejections", "--image-id", str(image.id))

        bad_category.refresh_from_db()
        assert bad_category.rejected_by.count() == 3  # not double-voted

    def test_sweep_survives_orphaned_child_created_by_a_mid_list_rejecter(self, image, creator):
        """
        Regression test: if one of a bbox's several historical rejecters is
        also the creator of an orphaned child (e.g. they tagged a species on
        this bbox in an earlier round, then rejected the bbox itself in a
        later round), vote()'s self-reject-with-no-accepts edge case deletes
        that child mid-loop. Voting the *next* rejecter onto the now-deleted
        (pk=None) object used to raise a ValueError from the M2M manager and
        crash the whole sweep. The fix stops voting on a child once it's
        deleted instead of continuing to the remaining rejecters.
        """
        image.processed = True
        image.save()

        bad_bbox = BoundingBox.objects.create(image=image, x=0.6, y=0.6, w=0.2, h=0.2, created_by=creator)

        tagger_user = User.objects.create_user(email="tagger@test.com", password="pass")
        tagger, _ = Annotator.objects.get_or_create(type="human", human=tagger_user)
        bad_category = Category.objects.create(bounding_box=bad_bbox, name="vehicle", created_by=tagger)

        rejecter0_user = User.objects.create_user(email="rejecter0@test.com", password="pass")
        rejecter0, _ = Annotator.objects.get_or_create(type="human", human=rejecter0_user)
        rejecter2_user = User.objects.create_user(email="rejecter2@test.com", password="pass")
        rejecter2, _ = Annotator.objects.get_or_create(type="human", human=rejecter2_user)

        # tagger (the orphaned category's own creator) rejects the bbox
        # *between* two other rejecters -- this ordering is what triggers
        # the crash if the child isn't deleted-and-stopped-on cleanly.
        for rejecter in (rejecter0, tagger, rejecter2):
            vote(bad_bbox, rejecter, accept=False)

        call_command("backfill_orphaned_bbox_rejections", "--image-id", str(image.id))  # must not raise

        assert not Category.objects.filter(id=bad_category.id).exists()
        bad_bbox.refresh_from_db()
        image.refresh_from_db()
        assert bad_bbox.validity in (None, "UNSEEN")  # no children left -> UNSEEN
        assert image.category_pipeline_complete is True

    def test_sweep_leaves_healthy_images_alone(self, image, creator):
        image.processed = True
        image.save()
        bbox = BoundingBox.objects.create(image=image, x=0.1, y=0.1, w=0.3, h=0.3, created_by=creator)
        category = Category.objects.create(bounding_box=bbox, name="vehicle", created_by=creator)
        accepter_user = User.objects.create_user(email="accepter@test.com", password="pass")
        accepter, _ = Annotator.objects.get_or_create(type="human", human=accepter_user)
        vote(category, accepter, accept=True)

        calculateCategoryAnnotationFlags(image)
        image.save()
        assert image.category_pipeline_complete is True

        call_command("backfill_orphaned_bbox_rejections", "--image-id", str(image.id))

        category.refresh_from_db()
        assert category.rejected_by.count() == 0
