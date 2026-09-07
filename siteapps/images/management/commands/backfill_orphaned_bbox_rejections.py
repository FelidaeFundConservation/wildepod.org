"""
One-off fix-forward command for images stuck unresolved because a rejected
bounding box's children were never voted on directly.

Before the fix to handle_bbox_deletions() (processors/annotation.py), a
volunteer rejecting a bogus/duplicate bounding box (by omitting it from
their submission) only recorded a vote on the bbox's own accepted_by /
rejected_by M2M -- it never touched the bbox's Category / Species / Activity
children. An orphaned child that nobody separately voted on sits at
UNCERTAIN forever (only its creator's implicit vote contributes to its
score), which blocks category_pipeline_complete -- and everything
downstream -- for the *whole image*, no matter how many votes the image's
real annotations have. See VOTING_LOGIC.md for the consensus model this
restores rather than bypasses.

This command finds bounding boxes that were rejected under the old
behavior (bbox.rejected_by non-empty) but whose Category / Species /
Activity children were never directly voted on (accepted_by and
rejected_by both empty), and retroactively casts the same reject votes
those bbox-rejecters gave onto the orphaned children -- exactly what
handle_bbox_deletions() now does going forward. It then re-runs
calculate*AnnotationFlags for every affected image so previously-stuck
images can resolve.

Idempotent: once a child has been voted on (or an image has no orphaned
rejected bboxes left) it's a no-op on re-run.

Usage:
    python manage.py backfill_orphaned_bbox_rejections --dry-run
    python manage.py backfill_orphaned_bbox_rejections
    python manage.py backfill_orphaned_bbox_rejections --image-id=<uuid>
"""

import time

from django.core.management.base import BaseCommand
from django.db import transaction
from images.models import Image
from images.processors.annotation import vote
from images.views.annotation import (
    calculateActivityAnnotationFlags,
    calculateCategoryAnnotationFlags,
    calculateSpeciesAnnotationFlags,
)


class Command(BaseCommand):
    help = "Fix images stuck unresolved because a rejected bbox's children were never voted on (pre-fix behavior)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
        parser.add_argument("--batch-size", type=int, default=200, help="Images per batch. Default 200.")
        parser.add_argument("--image-id", type=str, help="Limit to a single image (for spot-checking).")
        parser.add_argument(
            "--verbose-bboxes", action="store_true", help="Log every fixed bbox, not just per-batch progress."
        )

    def handle(self, *args, dry_run=False, batch_size=200, image_id=None, verbose_bboxes=False, **opts):
        if image_id:
            image_ids = [image_id]
        else:
            image_ids = list(
                Image.objects.filter(boundingbox__rejected_by__isnull=False).values_list("id", flat=True).distinct()
            )
        self.stdout.write(f"Scanning {len(image_ids):,} image(s) with at least one rejected bounding box...")

        fixed_bboxes = 0
        touched_images = 0
        scanned_images = 0
        start_time = time.monotonic()

        for i in range(0, len(image_ids), batch_size):
            batch_image_ids = image_ids[i : i + batch_size]
            images = Image.objects.filter(id__in=batch_image_ids).prefetch_related(
                "boundingbox_set__category_set__accepted_by",
                "boundingbox_set__category_set__rejected_by",
                "boundingbox_set__species_set__accepted_by",
                "boundingbox_set__species_set__rejected_by",
                "boundingbox_set__activity_set__accepted_by",
                "boundingbox_set__activity_set__rejected_by",
                "boundingbox_set__rejected_by",
            )
            for image in images:
                image_changed = False
                for bbox in image.boundingbox_set.all():
                    rejecters = list(bbox.rejected_by.all())
                    if not rejecters:
                        continue

                    # len(child.accepted_by.all()) (not .count()) so this reads from the
                    # prefetch cache instead of issuing a fresh query per child -- at prod
                    # scale (hundreds of thousands of rejected bboxes) .count() here turns
                    # into millions of extra round trips.
                    orphaned_children = [
                        child
                        for children in (bbox.category_set.all(), bbox.species_set.all(), bbox.activity_set.all())
                        for child in children
                        if len(child.accepted_by.all()) == 0 and len(child.rejected_by.all()) == 0
                    ]
                    if not orphaned_children:
                        continue

                    fixed_bboxes += 1
                    image_changed = True
                    if verbose_bboxes:
                        self.stdout.write(
                            f"  bbox {bbox.id} (image {image.id}): propagating {len(rejecters)} reject "
                            f"vote(s) onto {len(orphaned_children)} orphaned child annotation(s)"
                        )
                    if not dry_run:
                        for child in orphaned_children:
                            for annotator in rejecters:
                                vote(child, annotator, accept=False)

                if image_changed:
                    touched_images += 1
                    if not dry_run:
                        with transaction.atomic():
                            calculateCategoryAnnotationFlags(image)
                            calculateSpeciesAnnotationFlags(image)
                            calculateActivityAnnotationFlags(image)
                            image.save()

            scanned_images += len(batch_image_ids)
            elapsed = time.monotonic() - start_time
            rate = scanned_images / elapsed if elapsed > 0 else 0
            self.stdout.write(
                f"  progress: {scanned_images:,}/{len(image_ids):,} images scanned "
                f"({rate:.0f}/sec, elapsed {elapsed:.0f}s) -- "
                f"{fixed_bboxes:,} bboxes / {touched_images:,} images fixed so far"
            )
            self.stdout.flush()

        verb = "Would touch" if dry_run else "Touched"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {fixed_bboxes:,} bounding boxes across {touched_images:,} images.")
        )
        if dry_run:
            self.stdout.write("Dry run -- no changes written. Re-run without --dry-run to apply.")
