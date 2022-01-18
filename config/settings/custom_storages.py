from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage


class StaticStorage(GoogleCloudStorage):
    bucket_name = settings.GS_STATIC_STORAGE_BUCKET_NAME


class MediaStorage(GoogleCloudStorage):
    bucket_name = settings.GS_MEDIA_STORAGE_BUCKET_NAME
