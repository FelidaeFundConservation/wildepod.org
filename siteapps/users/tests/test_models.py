"""
Tests for User model.
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestUserModel:
    """Test User model functionality."""
    
    def test_user_creation(self):
        """Test creating a user."""
        user = User.objects.create_user(
            email="newuser@example.com",
            password="testpass123"
        )
        assert user.email == "newuser@example.com"
        assert user.check_password("testpass123")
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser
    
    def test_superuser_creation(self):
        """Test creating a superuser."""
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123"
        )
        assert admin_user.is_active
        assert admin_user.is_staff
        assert admin_user.is_superuser
    
    def test_user_str_representation(self, user):
        """Test user string representation."""
        # User str returns the name field
        assert str(user) == user.name
    
    def test_user_email_is_normalized(self):
        """Test that email is normalized."""
        email = "test@EXAMPLE.COM"
        user = User.objects.create_user(
            email=email,
            password="testpass123"
        )
        assert user.email == "test@example.com"


@pytest.mark.django_db
def test_user_fixture(user):
    """Test that user fixture works correctly."""
    assert user.email == "testuser@example.com"
    assert user.check_password("testpass123")


@pytest.mark.django_db
def test_staff_user_fixture(staff_user):
    """Test that staff_user fixture works correctly."""
    assert staff_user.is_staff
    assert not staff_user.is_superuser


@pytest.mark.django_db
def test_superuser_fixture(superuser):
    """Test that superuser fixture works correctly."""
    assert superuser.is_staff
    assert superuser.is_superuser
