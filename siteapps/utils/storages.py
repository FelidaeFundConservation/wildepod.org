from django.core.files.storage import get_storage_class
from storages.backends.gcloud import GoogleCloudStorage


class MediaRootGoogleCloudStorage(GoogleCloudStorage):
    location = "media"
    default_acl = "publicRead"
