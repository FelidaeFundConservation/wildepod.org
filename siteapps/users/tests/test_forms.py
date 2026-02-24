"""
Test cases for user forms.
"""
import pytest
from django.contrib.auth import get_user_model
from users.forms import UserAdminCreationForm, UserAdminChangeForm, RegisterVolunteerForm

User = get_user_model()


@pytest.mark.django_db
class TestUserAdminCreationForm:
    """Test UserAdminCreationForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {
            'email': 'newuser@example.com',
            'name': 'New User',
            'password1': 'testpass123!',
            'password2': 'testpass123!',
        }
        form = UserAdminCreationForm(data=form_data)
        
        assert form.is_valid()
        user = form.save()
        assert user.email == 'newuser@example.com'
        assert user.name == 'New User'
        assert user.check_password('testpass123!')

    def test_duplicate_email(self):
        """Test form with duplicate email."""
        User.objects.create_user(email='existing@example.com', password='pass123')
        
        form_data = {
            'email': 'existing@example.com',
            'name': 'Duplicate User',
            'password1': 'testpass123!',
            'password2': 'testpass123!',
        }
        form = UserAdminCreationForm(data=form_data)
        
        assert not form.is_valid()
        assert 'email' in form.errors

    def test_password_mismatch(self):
        """Test form with mismatched passwords."""
        form_data = {
            'email': 'test@example.com',
            'name': 'Test User',
            'password1': 'testpass123!',
            'password2': 'differentpass123!',
        }
        form = UserAdminCreationForm(data=form_data)
        
        assert not form.is_valid()
        assert 'password2' in form.errors

    def test_missing_email(self):
        """Test form without email."""
        form_data = {
            'name': 'Test User',
            'password1': 'testpass123!',
            'password2': 'testpass123!',
        }
        form = UserAdminCreationForm(data=form_data)
        
        assert not form.is_valid()
        assert 'email' in form.errors


@pytest.mark.django_db
class TestUserAdminChangeForm:
    """Test UserAdminChangeForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        user = User.objects.create_user(
            email='original@example.com',
            password='pass123',
            name='Original Name'
        )
        
        form_data = {
            'email': 'updated@example.com',
            'name': 'Updated Name',
        }
        form = UserAdminChangeForm(data=form_data, instance=user)
        
        assert form.is_valid()
        updated_user = form.save()
        assert updated_user.email == 'updated@example.com'
        assert updated_user.name == 'Updated Name'

    def test_change_only_name(self):
        """Test changing only the name field."""
        user = User.objects.create_user(
            email='test@example.com',
            password='pass123',
            name='Old Name'
        )
        
        form_data = {
            'email': 'test@example.com',
            'name': 'New Name',
        }
        form = UserAdminChangeForm(data=form_data, instance=user)
        
        assert form.is_valid()
        updated_user = form.save()
        assert updated_user.email == 'test@example.com'
        assert updated_user.name == 'New Name'


@pytest.mark.django_db
class TestRegisterVolunteerForm:
    """Test RegisterVolunteerForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {
            'email': 'volunteer@example.com',
            'name': 'John Volunteer',
            'phone_number': '555-1234',
        }
        form = RegisterVolunteerForm(data=form_data)
        
        assert form.is_valid()
        assert form.cleaned_data['email'] == 'volunteer@example.com'
        assert form.cleaned_data['name'] == 'John Volunteer'
        assert form.cleaned_data['phone_number'] == '555-1234'

    def test_email_only(self):
        """Test form with only email (name and phone are optional)."""
        form_data = {
            'email': 'minimal@example.com',
        }
        form = RegisterVolunteerForm(data=form_data)
        
        assert form.is_valid()
        assert form.cleaned_data['email'] == 'minimal@example.com'
        assert form.cleaned_data['name'] == ''
        assert form.cleaned_data['phone_number'] == ''

    def test_missing_email(self):
        """Test form without required email."""
        form_data = {
            'name': 'John Doe',
            'phone_number': '555-1234',
        }
        form = RegisterVolunteerForm(data=form_data)
        
        assert not form.is_valid()
        assert 'email' in form.errors

    def test_invalid_email(self):
        """Test form with invalid email format."""
        form_data = {
            'email': 'not-an-email',
            'name': 'Test User',
        }
        form = RegisterVolunteerForm(data=form_data)
        
        assert not form.is_valid()
        assert 'email' in form.errors

    def test_empty_form(self):
        """Test completely empty form."""
        form = RegisterVolunteerForm(data={})
        
        assert not form.is_valid()
        assert 'email' in form.errors
