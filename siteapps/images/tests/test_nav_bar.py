# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Guards for the shared nav bar.

The bar lives in _base.html, which 48 templates extend, and its pending-upload
badge is fed by a context processor that runs on every single request. That
makes it unlike an ordinary feature: a mistake here is not one broken page, it
is every page. These tests pin the properties that keep that safe.
"""
from unittest.mock import patch

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from siteapps.conftest_factories import UploadFactory


@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="navstaff@example.com", password="x", name="Nav Staff", is_staff=True
    )


class TestNavRendersForEveryRole:
    """_base.html must render for anyone who can reach any page at all."""

    def test_renders_for_anonymous(self, client, db):
        assert client.get(reverse("account_login")).status_code == 200

    def test_renders_for_volunteer(self, client, user):
        client.force_login(user)
        assert client.get(reverse("home:index")).status_code == 200

    def test_renders_for_staff(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse("home:index")).status_code == 200

    def test_renders_for_expert(self, client, user):
        user.is_expert = True
        user.save()
        client.force_login(user)
        assert client.get(reverse("home:index")).status_code == 200


class TestBadgeVisibility:
    def test_absent_with_nothing_pending(self, client, user):
        client.force_login(user)
        assert b"nav-pending-badge" not in client.get(reverse("home:index")).content

    def test_present_and_counts_correctly(self, client, user):
        for _ in range(3):
            UploadFactory(volunteer=user, upload_complete=False)
        client.force_login(user)
        body = client.get(reverse("home:index")).content.decode()
        assert "nav-pending-badge" in body
        assert ">3</span>" in body

    def test_staff_are_not_shown_other_peoples_uploads(self, client, staff_user):
        """The list page shows staff everyone's pending uploads; the badge is a
        personal to-do and must not inherit that."""
        UploadFactory(upload_complete=False)  # someone else's
        client.force_login(staff_user)
        assert b"nav-pending-badge" not in client.get(reverse("home:index")).content


class TestNeverBreaksThePage:
    """500.html extends _base.html, so the processor runs while the error page
    renders. If it can raise, a database failure costs you the error page too."""

    def test_survives_a_database_failure(self, rf, user):
        from images.context_processors import pending_uploads

        request = rf.get("/")
        request.user = user
        with patch("images.context_processors.Upload") as mock_upload:
            mock_upload.objects.filter.side_effect = Exception("database is down")
            assert pending_uploads(request) == {"nav_pending_upload_count": 0}

    def test_page_still_renders_when_the_badge_query_fails(self, client, user):
        client.force_login(user)
        with patch("images.context_processors.Upload") as mock_upload:
            mock_upload.objects.filter.side_effect = Exception("database is down")
            assert client.get(reverse("home:index")).status_code == 200


class TestQueryBudget:
    """Runs on every page, so its cost is paid site-wide. Keep it to one
    indexed COUNT; a regression here is a site-wide slowdown, not a local one."""

    def test_badge_adds_at_most_two_queries(self, client, user):
        UploadFactory(volunteer=user, upload_complete=False)
        client.force_login(user)
        with CaptureQueriesContext(connection) as ctx:
            client.get(reverse("home:index"))
        upload_queries = [q for q in ctx.captured_queries if "images_upload" in q["sql"]]
        # One COUNT, plus one row fetch only in the single-upload deep-link case.
        assert len(upload_queries) <= 2, [q["sql"] for q in upload_queries]

    def test_costs_nothing_for_anonymous_visitors(self, client, db):
        with CaptureQueriesContext(connection) as ctx:
            client.get(reverse("account_login"))
        assert not [q for q in ctx.captured_queries if "images_upload" in q["sql"]]
