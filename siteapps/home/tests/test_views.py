"""
Test cases for home views.
"""
import pytest
from django.urls import reverse
from django.test import Client


@pytest.mark.django_db
class TestHomeView:
    """Test home page view."""

    def test_home_view_accessible(self, client):
        """Test that home page is accessible."""
        response = client.get(reverse('home:index'))
        assert response.status_code == 200

    def test_home_view_uses_correct_template(self, client):
        """Test that home page uses correct template."""
        response = client.get(reverse('home:index'))
        assert 'home/home.html' in [t.name for t in response.templates]

    def test_home_view_anonymous_user(self):
        """Test home page accessible to anonymous users."""
        client = Client()
        response = client.get(reverse('home:index'))
        assert response.status_code == 200

    def test_home_view_authenticated_user(self, authenticated_client):
        """Test home page accessible to authenticated users."""
        response = authenticated_client.get(reverse('home:index'))
        assert response.status_code == 200
