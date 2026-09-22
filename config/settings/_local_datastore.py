# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""In-memory stand-in for the Google Cloud Datastore client, for local development only.

Production and staging use a real ``datastore.Client`` (see ``base.py``). Local settings
previously set ``DATASTORE_CLIENT = None``, which made every annotation view raise
``AttributeError: 'NoneType' object has no attribute 'key'`` as soon as it tried to read
the annotation queue.

This shim implements only the surface the codebase actually touches:
``key()``, ``get()``, ``put()``, ``delete()`` and ``entity()``.

State lives in process memory, so it is cleared whenever the dev server restarts (which
the autoreloader does on every code edit). That is fine for local use -- the annotation
views treat a missing queue as "gather a fresh one".
"""

import threading


class LocalEntity(dict):
    """Mimics ``google.cloud.datastore.Entity``: a dict that carries a ``key``."""

    def __init__(self, key=None, exclude_from_indexes=(), **kwargs):
        super().__init__(**kwargs)
        self.key = key
        self.exclude_from_indexes = set(exclude_from_indexes)


class LocalDatastoreClient:
    """Thread-safe, in-memory replacement for ``datastore.Client``.

    ``runserver`` is threaded, so requests can land concurrently; a lock keeps the
    backing dict consistent.
    """

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def key(self, *path_args, **kwargs):
        # The real client returns a Key object. Callers only ever pass these straight
        # back into get/put/delete, so an immutable tuple is a sufficient stand-in.
        return tuple(path_args)

    def entity(self, key=None, exclude_from_indexes=(), **kwargs):
        return LocalEntity(key=key, exclude_from_indexes=exclude_from_indexes, **kwargs)

    def get(self, key):
        with self._lock:
            stored = self._store.get(tuple(key) if key is not None else None)
            if stored is None:
                return None
            # Hand back a copy so callers mutating the result do not implicitly write
            # through to the store before they call put(), matching the real client.
            clone = LocalEntity(key=stored.key)
            clone.update(stored)
            return clone

    def put(self, entity):
        key = getattr(entity, "key", None)
        with self._lock:
            stored = LocalEntity(key=key)
            stored.update(entity)
            self._store[tuple(key) if key is not None else None] = stored

    def delete(self, key):
        with self._lock:
            self._store.pop(tuple(key) if key is not None else None, None)
