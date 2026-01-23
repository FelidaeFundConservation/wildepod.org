# Manual migration to add user_image_count field to Upload model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0052_add_query_optimization_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name='upload',
            name='user_image_count',
            field=models.IntegerField(null=True, blank=True, help_text="Number of images reported by user when creating upload"),
        ),
        migrations.AddField(
            model_name='historicalupload',
            name='user_image_count',
            field=models.IntegerField(null=True, blank=True, help_text="Number of images reported by user when creating upload"),
        ),
    ]
