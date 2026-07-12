# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from django.core.files.storage import get_storage_class
from storages.backends.gcloud import GoogleCloudStorage


class MediaRootGoogleCloudStorage(GoogleCloudStorage):
    location = "media"
    default_acl = "publicRead"
