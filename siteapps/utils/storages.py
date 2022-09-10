from django.core.files.storage import get_storage_class
from storages.backends.gcloud import GoogleCloudStorage


class StaticRootGoogleCloudStorage(GoogleCloudStorage):
    location = "static"
    default_acl = "publicRead"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_storage = get_storage_class("compressor.storage.CompressorFileStorage")()

    def save(self, name, content):
        self.local_storage._save(name, content)
        super().save(name, self.local_storage._open(name))
        return name


class MediaRootGoogleCloudStorage(GoogleCloudStorage):
    location = "media"
    default_acl = "publicRead"
