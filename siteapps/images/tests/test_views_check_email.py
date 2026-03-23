"""Tests for images.views.check_email module"""

import pytest
import datetime
import email
from unittest.mock import patch, MagicMock, Mock
from django.urls import reverse
from django.contrib.auth import get_user_model
from images.views.check_email import CheckDropbox2FAEmailView

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass123"
    )


@pytest.fixture
def view():
    """Create a CheckDropbox2FAEmailView instance."""
    return CheckDropbox2FAEmailView()


@pytest.mark.django_db
class TestCheckDropbox2FAEmailView:
    """Test CheckDropbox2FAEmailView class methods."""
    
    def test_get_body_plain_message(self, view):
        """Test getting body from plain text message."""
        # Create a plain text email message
        msg = email.message.Message()
        msg.set_payload("This is a test message")
        
        result = view.get_body(msg)
        assert result == b"This is a test message"
    
    def test_get_body_multipart_message(self, view):
        """Test getting body from multipart message."""
        # Create a multipart message
        msg = email.message.EmailMessage()
        msg.set_content("This is the first part")
        msg.add_alternative("<html><body>HTML part</body></html>", subtype='html')
        
        result = view.get_body(msg)
        # Should return the first part
        assert result is not None
    
    def test_parse_email_with_valid_code(self, view):
        """Test parsing email with valid security code."""
        test_message = """
        Here is your security code for Dropbox:
        
        123456
        
        We noticed a new login attempt.
        """
        
        result = view.parse_email(test_message)
        assert result == "123456"
    
    def test_parse_email_without_code(self, view):
        """Test parsing email without security code."""
        test_message = "This is just a regular email without any code."
        
        result = view.parse_email(test_message)
        assert result is None
    
    def test_parse_email_with_different_format(self, view):
        """Test parsing email with code but different format."""
        test_message = "Random text before security code is 987654 and We noticed something"
        
        result = view.parse_email(test_message)
        assert result == "987654"
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_get_last_email_success(self, mock_settings, mock_imap, view):
        """Test getting last email successfully."""
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection
        mock_con = MagicMock()
        mock_imap.return_value = mock_con
        
        # Mock search results
        mock_con.search.return_value = ("OK", [b"1 2 3"])
        
        # Create a test email message
        test_email = email.message.EmailMessage()
        test_email["Date"] = datetime.datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
        test_email.set_content("Test email content")
        
        # Mock fetch
        mock_con.fetch.return_value = ("OK", [(None, test_email.as_bytes())])
        
        # Call method
        result = view.get_last_email("no-reply@dropbox.com", mock_con)
        
        # Should return email content
        assert result is not None
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_get_last_email_no_messages(self, mock_settings, mock_imap, view):
        """Test getting last email when no messages found."""
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection
        mock_con = MagicMock()
        mock_imap.return_value = mock_con
        
        # Mock empty search results
        mock_con.search.return_value = ("OK", [b""])
        
        # Call method
        result = view.get_last_email("no-reply@dropbox.com", mock_con)
        
        # Should return None
        assert result is None
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_get_last_email_old_message(self, mock_settings, mock_imap, view):
        """Test getting last email when message is too old."""
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection
        mock_con = MagicMock()
        mock_imap.return_value = mock_con
        
        # Mock search results
        mock_con.search.return_value = ("OK", [b"1"])
        
        # Create an old email (more than 10 minutes ago)
        old_date = datetime.datetime.now() - datetime.timedelta(minutes=15)
        test_email = email.message.EmailMessage()
        test_email["Date"] = old_date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        test_email.set_content("Old email content")
        
        # Mock fetch
        mock_con.fetch.return_value = ("OK", [(None, test_email.as_bytes())])
        
        # Call method
        result = view.get_last_email("no-reply@dropbox.com", mock_con)
        
        # Should return None for old messages
        assert result is None
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_post_success_with_code(self, mock_settings, mock_imap, client, user):
        """Test POST request returns code successfully."""
        client.force_login(user)
        
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection
        mock_con = MagicMock()
        mock_imap.return_value = mock_con
        
        # Mock login and select
        mock_con.login.return_value = ("OK", [])
        mock_con.select.return_value = ("OK", [])
        
        # Mock search results
        mock_con.search.return_value = ("OK", [b"1"])
        
        # Create a recent email with security code
        recent_date = datetime.datetime.now() - datetime.timedelta(minutes=2)
        
        # Create a proper multipart email
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        test_email = MIMEMultipart()
        test_email["Date"] = recent_date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        test_email["From"] = "no-reply@dropbox.com"
        test_email["Subject"] = "Your Dropbox security code"
        
        # Add text part with security code
        body_text = "Your security code for Dropbox is 123456. We noticed a login attempt."
        test_email.attach(MIMEText(body_text, 'plain'))
        
        # Mock fetch
        mock_con.fetch.return_value = ("OK", [(None, test_email.as_bytes())])
        
        # Make POST request
        url = reverse('images:check_dropbox_2fa_email')
        response = client.post(url)
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["code"] == "123456"
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_post_no_code_found(self, mock_settings, mock_imap, client, user):
        """Test POST request when no code is found."""
        client.force_login(user)
        
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection
        mock_con = MagicMock()
        mock_imap.return_value = mock_con
        
        # Mock login and select
        mock_con.login.return_value = ("OK", [])
        mock_con.select.return_value = ("OK", [])
        
        # Mock empty search results
        mock_con.search.return_value = ("OK", [b""])
        
        # Make POST request
        url = reverse('images:check_dropbox_2fa_email')
        response = client.post(url)
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["code"] == "NONE"
    
    def test_post_requires_authentication(self, client):
        """Test that POST requires user to be logged in."""
        url = reverse('images:check_dropbox_2fa_email')
        response = client.post(url)
        
        # Should redirect to login
        assert response.status_code == 302
        assert 'login' in response.url.lower()


@pytest.mark.django_db
class TestCheckDropbox2FAEmailViewEdgeCases:
    """Test edge cases for CheckDropbox2FAEmailView."""
    
    @patch('images.views.check_email.imaplib.IMAP4_SSL')
    @patch('images.views.check_email.settings')
    def test_post_with_imap_connection_error(self, mock_settings, mock_imap, client, user):
        """Test POST when IMAP connection fails."""
        client.force_login(user)
        
        # Setup settings
        mock_settings.EMAIL_2FA_IMAP_URL = "imap.gmail.com"
        mock_settings.EMAIL_2FA_USER = "test@example.com"
        mock_settings.EMAIL_2FA_PASSWORD = "password"
        
        # Mock IMAP connection failure
        mock_imap.side_effect = Exception("Connection failed")
        
        # Make POST request
        url = reverse('images:check_dropbox_2fa_email')
        
        # Should raise exception or handle gracefully
        with pytest.raises(Exception):
            response = client.post(url)
    
    def test_parse_email_with_multiple_codes(self, view):
        """Test parsing email with multiple potential codes."""
        test_message = """
        First code: 123456
        Your security code for Dropbox is 789012. We noticed activity.
        Another code: 345678
        """
        
        result = view.parse_email(test_message)
        # Should match the first valid pattern
        assert result == "789012"
    
    def test_parse_email_with_partial_pattern(self, view):
        """Test parsing email with partial matching pattern."""
        test_message = "security code but no number here. We noticed something."
        
        result = view.parse_email(test_message)
        assert result is None
