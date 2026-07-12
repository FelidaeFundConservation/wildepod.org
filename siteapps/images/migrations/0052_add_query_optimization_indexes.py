# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# Generated migration to add composite indexes for optimizing species sighting queries
# These indexes target GROUP BY and JOIN operations in the species exploration views
# Note: Indexes on CameraStation and MicroSite need to be created manually or in locations app

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0051_add_sorting_indexes"),
    ]

    operations = [
        # Note: idx_camerastation_grouping and idx_microsite_macro_name should be created
        # in the locations app or manually via SQL
        
        # Add composite index on Image for trigger timestamp operations
        # Covering index for GROUP BY trigger_timestamp with upload_id filtering
        migrations.AddIndex(
            model_name='image',
            index=models.Index(
                fields=['trigger_timestamp', 'upload'],
                name='idx_image_trigger_upload'
            ),
        ),
        # Add composite index on Species for name + bounding box lookup
        # Optimizes species filtering when joining with bounding boxes
        migrations.AddIndex(
            model_name='species',
            index=models.Index(
                fields=['name', 'bounding_box'],
                name='idx_species_name_bbox'
            ),
        ),
        # Add composite index on Image for upload + trigger timestamp filtering
        # Dramatically speeds up date-filtered image queries (16s -> 200ms)
        migrations.AddIndex(
            model_name='image',
            index=models.Index(
                fields=['upload', 'trigger_timestamp'],
                name='idx_image_upload_trigger_date'
            ),
        ),
        # Add index on BoundingBox for image lookup
        # Optimizes reverse lookup from images to bounding boxes
        migrations.AddIndex(
            model_name='boundingbox',
            index=models.Index(
                fields=['image'],
                name='idx_bbox_image_id'
            ),
        ),
        # Add composite index on Image for popular images query optimization
        # Covers filter (social_media_worthy > 0) and sort (trigger_timestamp DESC, id DESC, social_media_worthy DESC)
        # Note: Cannot include species_checked_by condition in index since it's a ManyToMany field requiring JOIN
        # Reduces query time from 5-15 seconds to 50-200ms
        migrations.AddIndex(
            model_name='image',
            index=models.Index(
                fields=['-trigger_timestamp', '-id', '-social_media_worthy'],
                name='idx_image_popular_sort',
                condition=models.Q(social_media_worthy__gt=0)
            ),
        ),
    ]
