# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""A Dropbox client stand-in that models the folder namespace.

Mock() cannot express the thing the folder-reservation tests are about -- that a name free in the
database can still be taken in Dropbox -- because every attribute access returns a truthy Mock and
nothing ever conflicts. This refuses a second create on the same path the way Dropbox does, and
records what was created so a test can assert what was and was not touched.
"""

from unittest.mock import Mock

import dropbox


class FakeDropbox:
    def __init__(self, occupied=None):
        # path -> list of entry names. Contents are never consulted by the code under test --
        # they are here so a test can assert a foreign folder was left untouched.
        self.folders = dict(occupied or {})
        # path -> WriteConflictError kind, for paths blocked by something other than a folder
        self.conflicts = {}
        self.file_requests = []
        self.uploads = []
        self.create_attempts = 0

    def files_create_folder(self, path):
        self.create_attempts += 1
        if path in self.folders or path in self.conflicts:
            kind = self.conflicts.get(path, dropbox.files.WriteConflictError.folder)
            raise dropbox.exceptions.ApiError(
                request_id="req",
                error=dropbox.files.CreateFolderError.path(dropbox.files.WriteError.conflict(kind)),
                user_message_text=None,
                user_message_locale=None,
            )
        self.folders[path] = []
        return Mock(metadata=Mock(id="id:folder"))

    def file_requests_create(self, title, destination):
        self.file_requests.append((title, destination))
        return Mock(id=f"fr_{len(self.file_requests)}", url="https://dropbox.com/request", is_open=True)

    def files_upload(self, contents, path, **kwargs):
        self.uploads.append((path, contents))
        folder = "/" + path.lstrip("/").split("/")[0]
        self.folders.setdefault(folder, []).append(path)
        return Mock()


def base_folder_name(upload):
    """The folder name setup_dropbox_paths() generates before any collision handling."""
    return (
        f"{upload.date_retrieved.date()} - {upload.camera_station.micro_site.macro_site.name} -"
        f" {upload.camera_station.station_id}".lower()
    )
