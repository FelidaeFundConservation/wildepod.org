# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# Migration to add indexes for social media worthy images with species filtering
# Optimizes the query: Image -> BoundingBox -> Species -> SpeciesName filtering

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0053_add_user_image_count"),
    ]

    operations = [
        # Add composite index on Image for social_media_worthy filtering
        # Speeds up the base query for popular images page
        migrations.AddIndex(
            model_name='image',
            index=models.Index(
                fields=['social_media_worthy', 'trigger_timestamp', 'id'],
                name='idx_image_social_media_worthy'
            ),
        ),
        # Add composite index on Species for name_id + bounding_box lookup
        # Optimizes species filtering when joining with bounding boxes
        # This is crucial for the species filter query path
        migrations.AddIndex(
            model_name='species',
            index=models.Index(
                fields=['name_id', 'bounding_box_id'],
                name='idx_species_name_id_bbox'
            ),
        ),
        # Add composite index on BoundingBox for image + species lookup
        # Speeds up the join from Image to Species through BoundingBox
        migrations.AddIndex(
            model_name='boundingbox',
            index=models.Index(
                fields=['image_id'],
                name='idx_boundingbox_image_id'
            ),
        ),
    ]
