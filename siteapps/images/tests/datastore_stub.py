# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""In-memory stand-in for the Google Cloud Datastore client, for tests.

Production and staging use a real ``datastore.Client``; ``base.py`` sets
``DATASTORE_CLIENT = None`` everywhere else, which makes every annotation view raise
``AttributeError: 'NoneType' object has no attribute 'key'`` as soon as it reads the
annotation queue. The autouse ``datastore_client`` fixture in the root ``conftest.py``
swaps this in so any test that exercises an annotation view has a working queue.

It lives here rather than in local settings so that CI has it: settings files are per
developer and are not committed, and tests that depend on one fail everywhere else.

Implements only the surface the codebase touches: ``key()``, ``get()``, ``put()``,
``delete()`` and ``entity()``. State is per instance, so a fresh client per test keeps
queue state from leaking between them.
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

    The lock is there because the same class backs local ``runserver``, which is threaded.
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
