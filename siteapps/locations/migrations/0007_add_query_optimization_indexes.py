# Generated migration to add composite indexes for optimizing species sighting queries
# These indexes target GROUP BY operations in the species exploration views

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("locations", "0006_alter_historicalarea_options_and_more"),
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
        # Add composite index on MicroSite for macro site JOIN optimization
        # Optimizes microsite-to-macrosite relationships in species queries
        migrations.AddIndex(
            model_name='microsite',
            index=models.Index(
                fields=['macro_site', 'name'],
                name='idx_microsite_macro_name'
            ),
        ),
    ]
