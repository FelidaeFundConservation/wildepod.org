# Generated migration to add composite indexes for optimizing species sighting queries
# These indexes target GROUP BY and JOIN operations in the species exploration views

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0051_add_sorting_indexes"),
    ]

    operations = [
        # Add composite index on CameraStation for GROUP BY location columns
        # Optimizes grouping by micro_site_id, station_id, latitude, longitude
        migrations.AddIndex(
            model_name='camerastation',
            index=models.Index(
                fields=['micro_site', 'station_id', 'latitude', 'longitude'],
                name='idx_camerastation_grouping'
            ),
        ),
        # Add composite index on Image for trigger timestamp operations
        # Covering index for GROUP BY trigger_timestamp with upload_id filtering
        migrations.AddIndex(
            model_name='image',
            index=models.Index(
                fields=['trigger_timestamp', 'upload'],
                name='idx_image_trigger_upload'
            ),
        ),
        # Add composite index on MicroSite for macro site JOIN optimization
        # Optimizes microsite-to-macrosite relationships in species queries
        migrations.AddIndex(
            model_name='microsite',
            index=models.Index(
                fields=['macro_site', 'name'],
                name='idx_microsite_macro_name'
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
    ]
