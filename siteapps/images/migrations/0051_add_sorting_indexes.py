# Generated migration to add indexes for efficient sorting of species queries

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0050_alter_historicalcamerastationaction_options_and_more"),
    ]

    operations = [
        # Add index on images_species.modified for default ordering
        migrations.AddIndex(
            model_name='species',
            index=models.Index(fields=['-modified'], name='images_species_modified_idx'),
        ),
        # Add index on images_species.created for creation-time sorting
        migrations.AddIndex(
            model_name='species',
            index=models.Index(fields=['-created'], name='images_species_created_idx'),
        ),
        # Add composite index on (name_id, modified) for species-filtered sorted queries
        migrations.AddIndex(
            model_name='species',
            index=models.Index(fields=['name', '-modified'], name='images_species_name_modified_idx'),
        ),
        # Add index on images_boundingbox.modified for bounding box sorting
        migrations.AddIndex(
            model_name='boundingbox',
            index=models.Index(fields=['-modified'], name='images_bbox_modified_idx'),
        ),
        # Add index on images_boundingbox.created for creation-time sorting
        migrations.AddIndex(
            model_name='boundingbox',
            index=models.Index(fields=['-created'], name='images_bbox_created_idx'),
        ),
    ]
