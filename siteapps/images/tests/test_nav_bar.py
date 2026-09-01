# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Render guards for the shared nav bar.

_base.html is extended by 48 templates, and by 404.html and 500.html — so a
mistake in the bar is not one broken page, it is every page including the error
page you would need to diagnose it. These pin that it renders for everyone who
can reach any page at all.
"""
import pytest
from django.urls import reverse


@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="navstaff@example.com", password="x", name="Nav Staff", is_staff=True
    )


def test_renders_for_anonymous(client, db):
    assert client.get(reverse("account_login")).status_code == 200


def test_renders_for_volunteer(client, user):
    client.force_login(user)
    assert client.get(reverse("home:index")).status_code == 200


def test_renders_for_staff(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("home:index")).status_code == 200


def test_renders_for_expert(client, user):
    user.is_expert = True
    user.save()
    client.force_login(user)
    assert client.get(reverse("home:index")).status_code == 200


def test_uploads_page_still_renders(client, user):
    """The nav sits above every page; spot-check one beyond the home page."""
    client.force_login(user)
    assert client.get(reverse("images:list_uploads")).status_code == 200
