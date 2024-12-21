# 2db6e3bc-82fd-45a8-97f1-e627e84998ef
# python manage.py delete_upload --upload_id="2db6e3bc-82fd-45a8-97f1-e627e84998ef" --settings=config.settings.staging

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Delete an upload."

    def add_arguments(self, parser):
        parser.add_argument(
            "--upload_id",
            nargs="?",
            type=str,
            default=None,
            help="The id of the upload.",
        )

    def handle(self, *args, **options):
        upload_id = options.get("upload_id")

        from images.models import Image, Upload

        print(
            Upload.objects.filter(dropbox_folder_name__icontains="prs30a")
            .filter(dropbox_folder_name__icontains="2024-10-11")
            .values("id")
        )
