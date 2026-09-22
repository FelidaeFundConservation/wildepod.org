# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the nav-bar pending-upload badge context processor."""
import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from images.context_processors import pending_uploads
from siteapps.conftest_factories import UploadFactory


@pytest.fixture
def rf():
    return RequestFactory()


def _ctx(rf, user):
    request = rf.get("/")
    request.user = user
    return pending_uploads(request)


def test_anonymous_user_gets_nothing(rf):
    assert _ctx(rf, AnonymousUser()) == {}


def test_no_pending_uploads_reports_zero(rf, user, db):
    assert _ctx(rf, user)["nav_pending_upload_count"] == 0


def test_finalized_uploads_are_not_counted(rf, user, db):
    UploadFactory(volunteer=user, upload_complete=True)
    assert _ctx(rf, user)["nav_pending_upload_count"] == 0


def test_single_pending_upload_is_exposed_for_deep_linking(rf, user, db):
    upload = UploadFactory(volunteer=user, upload_complete=False)
    ctx = _ctx(rf, user)
    assert ctx["nav_pending_upload_count"] == 1
    assert ctx["nav_pending_upload"] == upload


def test_multiple_pending_uploads_count_but_do_not_deep_link(rf, user, db):
    for _ in range(3):
        UploadFactory(volunteer=user, upload_complete=False)
    ctx = _ctx(rf, user)
    assert ctx["nav_pending_upload_count"] == 3
    assert ctx["nav_pending_upload"] is None


def test_deleted_uploads_are_not_counted(rf, user, db):
    UploadFactory(volunteer=user, upload_complete=False, deleted=True)
    assert _ctx(rf, user)["nav_pending_upload_count"] == 0


def test_other_volunteers_uploads_are_not_counted(rf, user, db):
    """Staff see every pending upload on the list page, but the nav badge is a
    personal to-do and must stay scoped to the signed-in user."""
    user.is_staff = True
    user.save()
    UploadFactory(upload_complete=False)  # belongs to a different volunteer
    assert _ctx(rf, user)["nav_pending_upload_count"] == 0
