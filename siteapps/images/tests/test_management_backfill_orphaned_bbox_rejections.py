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
