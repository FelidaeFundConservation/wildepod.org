"""Tests for images.utils.dropbox_client module"""

import pytest
from unittest.mock import patch, MagicMock
from images.utils.dropbox_client import create_dropbox_client


@pytest.mark.django_db
class TestCreateDropboxClient:
    """Test the create_dropbox_client utility function"""
    
    @patch('images.utils.dropbox_client.dropbox.Dropbox')
    @patch('images.utils.dropbox_client.settings')
    def test_creates_client_with_valid_credentials(self, mock_settings, mock_dropbox):
        """Test that Dropbox client is created when all credentials are provided"""
        mock_settings.DROPBOX_APP_KEY = "test_app_key"
        mock_settings.DROPBOX_APP_SECRET = "test_app_secret"
        mock_settings.DROPBOX_REFRESH_TOKEN = "test_refresh_token"
        
        mock_dropbox_instance = MagicMock()
        mock_dropbox.return_value = mock_dropbox_instance
        
        result = create_dropbox_client()
        
        # Verify Dropbox was instantiated with correct parameters
        mock_dropbox.assert_called_once_with(
            app_key="test_app_key",
            app_secret="test_app_secret",
            oauth2_refresh_token="test_refresh_token",
        )
        assert result == mock_dropbox_instance
    
    @patch('images.utils.dropbox_client.settings')
    def test_returns_none_when_app_key_missing(self, mock_settings):
        """Test that None is returned when DROPBOX_APP_KEY is not configured"""
        mock_settings.DROPBOX_APP_KEY = None
        mock_settings.DROPBOX_APP_SECRET = "test_app_secret"
        mock_settings.DROPBOX_REFRESH_TOKEN = "test_refresh_token"
        
        result = create_dropbox_client()
        
        assert result is None
    
    @patch('images.utils.dropbox_client.settings')
    def test_returns_none_when_app_secret_missing(self, mock_settings):
        """Test that None is returned when DROPBOX_APP_SECRET is not configured"""
        mock_settings.DROPBOX_APP_KEY = "test_app_key"
        mock_settings.DROPBOX_APP_SECRET = None
        mock_settings.DROPBOX_REFRESH_TOKEN = "test_refresh_token"
        
        result = create_dropbox_client()
        
        assert result is None
    
    @patch('images.utils.dropbox_client.settings')
    def test_returns_none_when_refresh_token_missing(self, mock_settings):
        """Test that None is returned when DROPBOX_REFRESH_TOKEN is not configured"""
        mock_settings.DROPBOX_APP_KEY = "test_app_key"
        mock_settings.DROPBOX_APP_SECRET = "test_app_secret"
        mock_settings.DROPBOX_REFRESH_TOKEN = None
        
        result = create_dropbox_client()
        
        assert result is None
    
    @patch('images.utils.dropbox_client.settings')
    def test_returns_none_when_all_credentials_missing(self, mock_settings):
        """Test that None is returned when no credentials are configured"""
        mock_settings.DROPBOX_APP_KEY = None
        mock_settings.DROPBOX_APP_SECRET = None
        mock_settings.DROPBOX_REFRESH_TOKEN = None
        
        result = create_dropbox_client()
        
        assert result is None
    
    @patch('images.utils.dropbox_client.settings')
    def test_returns_none_with_empty_strings(self, mock_settings):
        """Test that None is returned when credentials are empty strings"""
        mock_settings.DROPBOX_APP_KEY = ""
        mock_settings.DROPBOX_APP_SECRET = ""
        mock_settings.DROPBOX_REFRESH_TOKEN = ""
        
        result = create_dropbox_client()
        
        assert result is None
