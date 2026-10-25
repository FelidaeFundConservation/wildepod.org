# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the Fundraise Up widget toggle in the global settings context processor."""
import pytest
from django.test import override_settings
from django.urls import reverse

FUNDRAISEUP_KEY = "TESTKEY1"


@pytest.fixture(autouse=True)
def fundraiseup_on():
    with override_settings(FUNDRAISEUP_ACCOUNT_KEY=FUNDRAISEUP_KEY):
        yield


def _has_fundraiseup(response):
    content = response.content.decode()
    return FUNDRAISEUP_KEY in content or "#?form=" in content


def test_widget_loads_on_regular_pages(client, db):
    response = client.get("/")
    assert response.status_code == 200
    assert _has_fundraiseup(response)


@pytest.mark.parametrize(
    "url",
    [
        reverse("account_confirm_email", args=["not-a-real-key"]),
        reverse("account_reset_password_from_key", kwargs={"uidb36": "1", "key": "not-a-real-key"}),
    ],
)
def test_widget_stays_off_pages_whose_url_carries_an_auth_key(client, db, url):
    response = client.get(url)
    assert response.status_code == 200
    assert not _has_fundraiseup(response)
