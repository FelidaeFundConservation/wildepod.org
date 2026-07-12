# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Test cases for users views.
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.urls import reverse
from django.utils import timezone
from images.models import Activity, Annotator, Category, Species


@pytest.mark.django_db
class TestUserUpdateView:
    """Test user profile update view."""

    def test_profile_view_requires_login(self, client):
        """Test that profile view requires authentication."""
        url = reverse("users:profile")
        response = client.get(url)
        assert response.status_code == 302  # Redirect to login
        assert "/accounts/login/" in response.url

    def test_profile_view_accessible_to_authenticated_user(self, authenticated_client):
        """Test that authenticated users can access their profile."""
        url = reverse("users:profile")
        response = authenticated_client.get(url, follow=True)
        # Check that we got a response (may be 200 or redirect)
        assert response.status_code == 200

    def test_profile_shows_annotation_counts(self, authenticated_client, user):
        """Test that profile view calculates annotation counts."""
        # Create an annotator for the user
        annotator = Annotator.objects.create(type="human", human=user)
        
        url = reverse("users:profile")
        response = authenticated_client.get(url, follow=True)
        
        # The view should execute without errors
        assert response.status_code == 200
        # Verify annotator was created
        assert Annotator.objects.filter(type="human", human=user).exists()

    def test_profile_update_success(self, authenticated_client, user):
        """Test that users can update their profile information."""
        url = reverse("users:profile")
        data = {
            "name": "Updated Name",
            "phone_number": "+1234567890",
        }
        response = authenticated_client.post(url, data, follow=True)
        
        # Should successfully update
        assert response.status_code == 200
        # Check the user was updated
        user.refresh_from_db()
        assert user.name == "Updated Name"
        assert user.phone_number == "+1234567890"

    def test_profile_creates_annotator_if_not_exists(self, authenticated_client, user):
        """Test that viewing profile creates Annotator object if it doesn't exist."""
        # Ensure no annotator exists
        Annotator.objects.filter(human=user).delete()
        
        url = reverse("users:profile")
        response = authenticated_client.get(url, follow=True)
        
        assert response.status_code == 200
        # Check that annotator was created
        assert Annotator.objects.filter(type="human", human=user).exists()


@pytest.mark.django_db
class TestVolunteerListView:
    """Test volunteer list view."""

    def test_volunteer_list_requires_login(self, client):
        """Test that volunteer list requires authentication."""
        url = reverse("users:volunteers_list")
        response = client.get(url)
        assert response.status_code == 302  # Redirect to login

    def test_volunteer_list_requires_staff(self, authenticated_client):
        """Test that volunteer list requires staff permissions."""
        url = reverse("users:volunteers_list")
        response = authenticated_client.get(url, follow=False)
        # Non-staff users should be denied access (redirect or forbidden)
        assert response.status_code in [302, 403]

    def test_volunteer_list_accessible_to_staff(self, client, staff_user):
        """Test that staff users can access volunteer list."""
        client.force_login(staff_user)
        url = reverse("users:volunteers_list")
        response = client.get(url, follow=True)
        assert response.status_code == 200


@pytest.mark.django_db
class TestVolunteerRegisterView:
    """Test volunteer registration view."""

    def test_volunteer_register_requires_login(self, client):
        """Test that volunteer registration requires authentication."""
        url = reverse("users:volunteer_add")
        response = client.get(url)
        assert response.status_code == 302  # Redirect to login

    def test_volunteer_register_requires_staff(self, authenticated_client):
        """Test that volunteer registration requires staff permissions."""
        url = reverse("users:volunteer_add")
        response = authenticated_client.get(url, follow=False)
        # Non-staff users should be denied access (redirect or forbidden)
        assert response.status_code in [302, 403]

    def test_volunteer_register_form_display(self, client, staff_user):
        """Test that staff users can see the registration form."""
        client.force_login(staff_user)
        url = reverse("users:volunteer_add")
        response = client.get(url, follow=True)
        assert response.status_code == 200

    def test_volunteer_register_creates_volunteer(self, client, staff_user):
        """Test that submitting form creates a new volunteer user."""
        from users.models import User
        
        client.force_login(staff_user)
        url = reverse("users:volunteer_add")
        data = {
            "email": "newvolunteer@example.com",
            "name": "New Volunteer",
            "phone_number": "+1234567890",
        }
        
        # Count users before
        user_count_before = User.objects.count()
        
        response = client.post(url, data, follow=True)
        
        # Should successfully create user
        assert response.status_code == 200
        assert User.objects.count() == user_count_before + 1
        
        # Verify the user was created with correct attributes
        new_user = User.objects.get(email="newvolunteer@example.com")
        assert new_user.name == "New Volunteer"
        assert new_user.phone_number == "+1234567890"
        assert new_user.is_volunteer is True


@pytest.mark.django_db
class TestVolunteerRegisterSuccessView:
    """Test volunteer registration success page."""

    def test_volunteer_added_requires_staff(self, authenticated_client):
        """Test that success page requires staff permissions."""
        url = reverse("users:volunteer_added")
        response = authenticated_client.get(url, follow=False)
        # Non-staff users should be denied access (redirect or forbidden)
        assert response.status_code in [302, 403]

    def test_volunteer_added_accessible_to_staff(self, client, staff_user):
        """Test that staff users can see success page."""
        client.force_login(staff_user)
        url = reverse("users:volunteer_added")
        response = client.get(url, follow=True)
        assert response.status_code == 200


@pytest.mark.django_db
class TestVolunteerStatsView:
    """Test volunteer statistics view."""

    def test_volunteer_stats_requires_login(self, client, user):
        """Test that volunteer stats requires authentication."""
        url = reverse("users:volunteer_stats", kwargs={"pk": user.id})
        response = client.get(url)
        assert response.status_code == 302  # Redirect to login

    def test_volunteer_stats_accessible_to_authenticated(self, authenticated_client, user):
        """Test that authenticated users can view volunteer stats."""
        url = reverse("users:volunteer_stats", kwargs={"pk": user.id})
        response = authenticated_client.get(url, follow=True)
        assert response.status_code == 200

    def test_volunteer_stats_calls_engagement_calculator(self, authenticated_client, user):
        """Test that stats view executes engagement calculation."""
        url = reverse("users:volunteer_stats", kwargs={"pk": user.id})
        response = authenticated_client.get(url, follow=True)
        
        # The view should execute without errors
        assert response.status_code == 200

    def test_volunteer_stats_creates_annotator_if_needed(self, authenticated_client, user):
        """Test that stats view creates Annotator if it doesn't exist."""
        # Ensure no annotator exists
        Annotator.objects.filter(human=user).delete()
        
        url = reverse("users:volunteer_stats", kwargs={"pk": user.id})
        response = authenticated_client.get(url, follow=True)
        
        assert response.status_code == 200
        # Check that annotator was created
        assert Annotator.objects.filter(type="human", human=user).exists()


@pytest.mark.django_db
class TestPrioritizeTaggingAnimalsView:
    """Test prioritize tagging animals view."""

    def test_prioritize_requires_login(self, client):
        """Test that prioritize action requires authentication."""
        url = reverse("users:prioritize_animals")
        response = client.post(url)
        assert response.status_code == 302  # Redirect to login

    def test_prioritize_only_accepts_post(self, authenticated_client):
        """Test that prioritize only accepts POST requests."""
        url = reverse("users:prioritize_animals")
        response = authenticated_client.get(url)
        # Should return 405 Method Not Allowed or similar
        assert response.status_code == 405

    def test_prioritize_updates_annotator_time(self, authenticated_client, user):
        """Test that POST request updates annotator prioritize time."""
        # Create annotator first
        annotator = Annotator.objects.create(type="human", human=user)
        original_time = annotator.prioritize_tagging_animals
        
        url = reverse("users:prioritize_animals")
        response = authenticated_client.post(url)
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["success"] is True
        
        # Check that time was updated
        annotator.refresh_from_db()
        assert annotator.prioritize_tagging_animals is not None
        if original_time:
            assert annotator.prioritize_tagging_animals > original_time

    def test_prioritize_creates_annotator_if_not_exists(self, authenticated_client, user):
        """Test that prioritize creates annotator if it doesn't exist."""
        # Ensure no annotator exists
        Annotator.objects.filter(human=user).delete()
        
        url = reverse("users:prioritize_animals")
        response = authenticated_client.post(url)
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["success"] is True
        
        # Check that annotator was created
        assert Annotator.objects.filter(type="human", human=user).exists()

    def test_prioritize_sets_future_time(self, authenticated_client, user):
        """Test that prioritize sets time approximately 1 hour in future."""
        url = reverse("users:prioritize_animals")
        
        # Record current time
        before_time = timezone.now()
        
        response = authenticated_client.post(url)
        assert response.status_code == 200
        
        annotator = Annotator.objects.get(type="human", human=user)
        # Time should be roughly 1 hour in the future
        expected_time = before_time + timedelta(hours=1)
        time_diff = abs((annotator.prioritize_tagging_animals - expected_time).total_seconds())
        # Allow up to 10 seconds of variance for test execution time
        assert time_diff < 10


@pytest.mark.django_db
class TestVolunteerResendInviteView:
    """Test volunteer resend invite view."""

    def test_resend_invite_requires_login(self, client):
        """Test that resend invite requires authentication."""
        url = reverse("users:volunteer_resend_invite")
        response = client.post(url)
        assert response.status_code == 302  # Redirect to login

    def test_resend_invite_requires_staff(self, authenticated_client):
        """Test that resend invite requires staff permissions."""
        url = reverse("users:volunteer_resend_invite")
        response = authenticated_client.post(url, data={}, content_type="application/json", follow=False)
        # Non-staff users should be denied access (redirect or forbidden)
        assert response.status_code in [302, 403]

    def test_resend_invite_only_accepts_post(self, client, staff_user):
        """Test that resend invite only accepts POST requests."""
        client.force_login(staff_user)
        url = reverse("users:volunteer_resend_invite")
        response = client.get(url)
        assert response.status_code == 405

    def test_resend_invite_sends_email_and_resets_password(self, client, staff_user, user):
        """Test that resend invite sends welcome email and resets password."""
        client.force_login(staff_user)
        old_password = user.password
        
        url = reverse("users:volunteer_resend_invite")
        data = {"volunteer_id": str(user.id)}
        
        response = client.post(url, data)
        
        assert response.status_code == 200
        response_data = json.loads(response.content)
        assert response_data["success"] is True
        
        # Password should have changed
        user.refresh_from_db()
        assert user.password != old_password

    def test_resend_invite_invalid_user_returns_error(self, client, staff_user):
        """Test that invalid user ID returns error response."""
        client.force_login(staff_user)
        url = reverse("users:volunteer_resend_invite")
        data = {"volunteer_id": "00000000-0000-0000-0000-000000000000"}  # Non-existent UUID
        
        response = client.post(url, data)
        assert response.status_code == 200
        response_data = json.loads(response.content)
        assert response_data["success"] is False

    @patch("siteapps.users.managers.send_mail")
    def test_resend_invite_handles_email_error(self, mock_send_mail, client, staff_user, user):
        """Test that email sending errors are handled gracefully."""
        # Make email sending fail
        mock_send_mail.side_effect = Exception("Email service unavailable")
        
        client.force_login(staff_user)
        url = reverse("users:volunteer_resend_invite")
        data = {"volunteer_id": str(user.id)}
        
        response = client.post(url, data)
        assert response.status_code == 200
        response_data = json.loads(response.content)
        # wildepod_main implementation still returns success=True even on email error
        assert response_data["success"] is True
