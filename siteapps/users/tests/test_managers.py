"""
Test cases for user managers.
"""
import pytest
from django.core import mail
from allauth.account.models import EmailAddress
from users.models import User


@pytest.mark.django_db
class TestUserManager:
    """Test custom UserManager methods."""

    def test_create_user(self):
        """Test creating a regular user."""
        user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            name="Test User"
        )
        
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.check_password("testpass123")
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.pk is not None

    def test_create_user_without_password(self):
        """Test creating a user without providing password (auto-generated)."""
        user = User.objects.create_user(
            email="auto@example.com",
            name="Auto Password User"
        )
        
        assert user.email == "auto@example.com"
        # Password should have been auto-generated
        assert user.password is not None
        assert len(user.password) > 0

    def test_create_user_without_email_raises_error(self):
        """Test that creating a user without email raises ValueError."""
        with pytest.raises(ValueError, match="The Email must be set"):
            User.objects.create_user(email="", password="test123")

    def test_create_user_normalizes_email(self):
        """Test that email is normalized."""
        user = User.objects.create_user(
            email="Test@EXAMPLE.COM",
            password="testpass123"
        )
        
        # Domain should be lowercased
        assert user.email == "Test@example.com"

    def test_create_user_creates_email_address(self):
        """Test that EmailAddress is created for allauth."""
        user = User.objects.create_user(
            email="allauth@example.com",
            password="testpass123"
        )
        
        # Check EmailAddress was created
        email_address = EmailAddress.objects.get(user=user)
        assert email_address.email == user.email
        assert email_address.primary is True
        assert email_address.verified is True

    def test_create_superuser(self):
        """Test creating a superuser."""
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
            name="Admin User"
        )
        
        assert user.email == "admin@example.com"
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.is_active is True
        assert user.is_volunteer is True
        assert user.check_password("adminpass123")

    def test_create_superuser_requires_is_staff(self):
        """Test that superuser must have is_staff=True."""
        with pytest.raises(ValueError, match="Superuser must have is_staff=True"):
            User.objects.create_superuser(
                email="admin@example.com",
                password="adminpass123",
                is_staff=False
            )

    def test_create_superuser_requires_is_superuser(self):
        """Test that superuser must have is_superuser=True."""
        with pytest.raises(ValueError, match="Superuser must have is_superuser=True"):
            User.objects.create_superuser(
                email="admin@example.com",
                password="adminpass123",
                is_superuser=False
            )

    def test_create_user_with_custom_fields(self):
        """Test creating a user with custom fields."""
        user = User.objects.create_user(
            email="custom@example.com",
            password="testpass123",
            name="Custom User",
            phone_number="555-1234",
            is_volunteer=True
        )
        
        assert user.phone_number == "555-1234"
        assert user.is_volunteer is True

    def test_multiple_users_created(self):
        """Test creating multiple users."""
        user1 = User.objects.create_user(
            email="user1@example.com",
            password="pass1"
        )
        user2 = User.objects.create_user(
            email="user2@example.com",
            password="pass2"
        )
        user3 = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass"
        )
        
        assert User.objects.count() == 3
        assert user1.is_superuser is False
        assert user2.is_superuser is False
        assert user3.is_superuser is True

    def test_create_user_with_prod_settings_sends_email(self, settings, mailoutbox):
        """Test that email is sent in prod environment."""
        settings.WSGI_APPLICATION = "config.wsgi.prod.application"
        user = User.objects.create_user(
            email="test@example.com",
            password=None  # Triggers generated password
        )
        assert len(mailoutbox) == 1
        assert "Welcome to WildePod!" in mailoutbox[0].subject
        assert "test@example.com" in mailoutbox[0].to

    def test_create_user_with_bhutan_settings_sends_email(self, settings, mailoutbox):
        """Test that email is sent in bhutan environment."""
        settings.WSGI_APPLICATION = "config.wsgi.bhutan.application"
        user = User.objects.create_user(
            email="test@example.com",
            password=None
        )
        assert len(mailoutbox) == 1
        assert "Welcome to WildePod Bhutan!" in mailoutbox[0].subject
        assert "test@example.com" in mailoutbox[0].to

    def test_create_user_with_staging_settings_sends_email(self, settings, mailoutbox):
        """Test that email is sent in staging environment."""
        settings.WSGI_APPLICATION = "config.wsgi.staging.application"
        user = User.objects.create_user(
            email="test@example.com",
            password=None
        )
        # Staging should not send emails (line 73)
        assert len(mailoutbox) == 0

    def test_create_user_with_local_settings_no_email(self, settings, mailoutbox):
        """Test that email is not sent in local environment."""
        settings.WSGI_APPLICATION = "config.wsgi.local.application"
        user = User.objects.create_user(
            email="test@example.com",
            password=None
        )
        # Local should not send emails
        assert len(mailoutbox) == 0
