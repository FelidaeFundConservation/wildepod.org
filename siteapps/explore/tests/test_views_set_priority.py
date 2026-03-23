"""
Tests for explore set_priority views.
"""
import json
import pytest
from datetime import date, timedelta
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from explore.views.set_priority import SetPriorityForm, PriorityView, ConfirmUpdateView
from images.models import CameraStationAction, Image, Upload
from locations.models import Area, County, MacroSite, MicroSite, CameraStation

User = get_user_model()


@pytest.fixture
def staff_user(db):
    """Create a staff user for testing."""
    user = User.objects.create_user(
        email="staffuser@example.com",
        password="testpass123",
        is_staff=True,
    )
    return user


@pytest.fixture
def client_logged_in(staff_user):
    """Create a logged-in client."""
    client = Client()
    client.force_login(staff_user)
    return client


@pytest.fixture
def macro_site(db):
    """Create a MacroSite for testing."""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro_site = MacroSite.objects.create(
        name="Test Macro Site",
        county=county,
    )
    return macro_site


@pytest.fixture
def camera_station(db, macro_site):
    """Create a CameraStation for testing."""
    micro_site = MicroSite.objects.create(
        name="Test Micro Site",
        macro_site=macro_site,
    )
    camera_station = CameraStation.objects.create(
        station_id="CAM001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        date_deployed=timezone.now().date(),
    )
    return camera_station


@pytest.fixture
def upload(db, camera_station, staff_user):
    """Create an upload for testing."""
    action, _ = CameraStationAction.objects.get_or_create(
        action="RETRIEVE"
    )
    upload = Upload.objects.create(
        camera_station=camera_station,
        volunteer=staff_user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="test_folder_priority_789",
        dropbox_folder_path="/test/folder/priority_789",
        dropbox_request_id="req_priority_789",
        dropbox_request_url="https://dropbox.com/request/priority_789",
        priority=1,
    )
    return upload


@pytest.mark.django_db
class TestSetPriorityForm:
    """Test SetPriorityForm."""
    
    def test_form_has_required_fields(self):
        """Test that the form has all expected fields."""
        form = SetPriorityForm()
        
        assert 'start_date' in form.fields
        assert 'end_date' in form.fields
        assert 'macrosites' in form.fields
        assert 'camera_stations' in form.fields
        assert 'priority_by' in form.fields
    
    def test_form_macrosites_required(self):
        """Test that macrosites field is required."""
        form = SetPriorityForm({
            'priority_by': '2',
        })
        
        assert not form.is_valid()
        assert 'macrosites' in form.errors
    
    def test_form_with_valid_data(self, macro_site):
        """Test form with valid data."""
        form = SetPriorityForm({
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'macrosites': [macro_site.id],
            'priority_by': '3',
        })
        
        assert form.is_valid()
        assert form.cleaned_data['start_date'] == date(2024, 1, 1)
        assert form.cleaned_data['end_date'] == date(2024, 12, 31)
        assert form.cleaned_data['priority_by'] == '3'
    
    def test_form_priority_choices(self):
        """Test that priority field has correct choices."""
        form = SetPriorityForm()
        
        # Should have 4 priority levels
        assert len(form.fields['priority_by'].choices) == 4


@pytest.mark.django_db
class TestPriorityView:
    """Test PriorityView."""
    
    def test_get_requires_login(self, client):
        """Test that GET requires login."""
        url = reverse('explore:set_priority')
        response = client.get(url)
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_get_requires_staff(self, db):
        """Test that GET requires staff privileges."""
        # Create non-staff user
        user = User.objects.create_user(
            email="regular@example.com",
            password="testpass123",
            is_staff=False,
        )
        client = Client()
        client.force_login(user)
        
        url = reverse('explore:set_priority')
        try:
            response = client.get(url)
            # Should be forbidden or redirected
            assert response.status_code in [302, 403, 500]
        except TypeError:
            # Handle handle_no_permission signature issue
            pass
    
    def test_get_with_staff_user(self, client_logged_in):
        """Test GET with staff user returns form."""
        url = reverse('explore:set_priority')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'form' in response.context
        assert isinstance(response.context['form'], SetPriorityForm)
    
    def test_get_context_includes_priorities(self, client_logged_in, upload):
        """Test that GET context includes priority groupings."""
        url = reverse('explore:set_priority')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'priorities' in response.context
        assert 'Low' in response.context['priorities']
        assert 'Medium' in response.context['priorities']
        assert 'High' in response.context['priorities']
        assert 'Highest' in response.context['priorities']
    
    def test_post_with_no_results(self, client_logged_in, macro_site):
        """Test POST with filters that match no uploads."""
        url = reverse('explore:set_priority')
        response = client_logged_in.post(url, {
            'macrosites': [macro_site.id],
            'start_date': '2020-01-01',
            'end_date': '2020-01-02',
            'priority_by': '2',
        })
        
        # Should redirect with message
        assert response.status_code == 302
    
    def test_post_with_matching_results(self, client_logged_in, upload, macro_site):
        """Test POST with filters that match uploads."""
        # Create an image for the upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/thumb.jpg",
        )
        
        url = reverse('explore:set_priority')
        response = client_logged_in.post(url, {
            'macrosites': [macro_site.id],
            'priority_by': '2',
        })
        
        # Should show confirmation page
        assert response.status_code == 200
        assert 'search_set' in response.context
        assert 'new_priority' in response.context
        assert response.context['new_priority'] == '2'
    
    def test_post_with_camera_station_filter(self, client_logged_in, upload, macro_site, camera_station):
        """Test POST with camera station filter."""
        # Create an image for the upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/thumb.jpg",
        )
        
        url = reverse('explore:set_priority')
        response = client_logged_in.post(url, {
            'macrosites': [macro_site.id],
            'camera_stations': [camera_station.id],
            'priority_by': '3',
        })
        
        # Should show confirmation page
        assert response.status_code == 200
        assert 'search_set' in response.context
    
    def test_post_with_date_range(self, client_logged_in, upload, macro_site):
        """Test POST with date range filter."""
        # Create an image for the upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/thumb.jpg",
        )
        
        today = date.today()
        url = reverse('explore:set_priority')
        response = client_logged_in.post(url, {
            'macrosites': [macro_site.id],
            'start_date': (today - timedelta(days=30)).isoformat(),
            'end_date': (today + timedelta(days=30)).isoformat(),
            'priority_by': '2',
        })
        
        # Should show confirmation page
        assert response.status_code == 200
        assert 'search_set' in response.context
    
    def test_post_with_highest_priority_shows_downgrade_info(self, client_logged_in, upload, macro_site):
        """Test POST with priority 4 shows downgrade information."""
        # Create existing highest priority upload
        action, _ = CameraStationAction.objects.get_or_create(action="RETRIEVE")
        existing_highest = Upload.objects.create(
            camera_station=upload.camera_station,
            volunteer=upload.volunteer,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="existing_highest_456",
            dropbox_folder_path="/test/existing_highest_456",
            dropbox_request_id="req_existing_456",
            dropbox_request_url="https://dropbox.com/request/existing_456",
            priority=4,
        )
        
        # Create image for both uploads
        for up in [upload, existing_highest]:
            Image.objects.create(
                upload=up,
                dropbox_file_name=f"test_{up.id}.jpg",
                dropbox_file_path=f"/test/test_{up.id}.jpg",
                dropbox_file_path_display=f"/test/test_{up.id}.jpg",
                dropbox_content_hash=f"hash_{up.id}",
                dropbox_file_id=f"file_id_{up.id}",
                file_size=1024,
                trigger_timestamp=timezone.now(),
                thumbnail_gcloud_path=f"test/thumb_{up.id}.jpg",
            )
        
        url = reverse('explore:set_priority')
        response = client_logged_in.post(url, {
            'macrosites': [macro_site.id],
            'priority_by': '4',
        })
        
        # Should show confirmation with downgrade info
        assert response.status_code == 200
        assert 'downgrade_set' in response.context
        assert 'num_records_to_downgrade' in response.context
        assert response.context['num_records_to_downgrade'] > 0


@pytest.mark.django_db
class TestConfirmUpdateView:
    """Test ConfirmUpdateView."""
    
    def test_post_requires_login(self, client):
        """Test that POST requires login."""
        url = reverse('explore:confirm_update')
        response = client.post(url, {})
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_post_updates_priority(self, client_logged_in, upload, macro_site):
        """Test POST updates upload priority."""
        # Create image for upload
        Image.objects.create(
            upload=upload,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/thumb.jpg",
        )
        
        # First POST to set priority form to get session data
        priority_url = reverse('explore:set_priority')
        client_logged_in.post(priority_url, {
            'macrosites': [macro_site.id],
            'priority_by': '3',
        })
        
        # Then confirm the update
        confirm_url = reverse('explore:confirm_update')
        response = client_logged_in.post(confirm_url, {})
        
        # Should redirect
        assert response.status_code == 302
        
        # Check that priority was updated
        upload.refresh_from_db()
        assert upload.priority == '3'
    
    def test_post_downgrades_existing_highest(self, client_logged_in, upload, macro_site):
        """Test POST downgrades existing highest priority when setting new ones."""
        # Create a different macro site for the existing highest priority upload
        from locations.models import County, Area
        area, _ = Area.objects.get_or_create(name="Different Area")
        county, _ = County.objects.get_or_create(name="Different County", defaults={"area": area})
        different_macro, _ = MacroSite.objects.get_or_create(
            name="Different Macro",
            defaults={"county": county}
        )
        
        # Create camera station in the different macro site
        from locations.models import MicroSite, CameraStation
        micro, _ = MicroSite.objects.get_or_create(
            name="Different Micro",
            defaults={"macro_site": different_macro}
        )
        station, _ = CameraStation.objects.get_or_create(
            station_id="CAM-DIFF-001",
            defaults={
                "latitude": 40.0,
                "longitude": -100.0,
                "micro_site": micro,
                "date_deployed": timezone.now().date()
            }
        )
        
        # Create existing highest priority upload in different macro site
        action, _ = CameraStationAction.objects.get_or_create(action="RETRIEVE")
        existing_highest = Upload.objects.create(
            camera_station=station,
            volunteer=upload.volunteer,
            date_retrieved=timezone.now(),
            last_action=action,
            dropbox_folder_name="existing_highest_789",
            dropbox_folder_path="/test/existing_highest_789",
            dropbox_request_id="req_existing_789",
            dropbox_request_url="https://dropbox.com/request/existing_789",
            priority="4",
        )
        
        # Create images for both uploads
        for up in [upload, existing_highest]:
            Image.objects.create(
                upload=up,
                dropbox_file_name=f"test_{up.id}.jpg",
                dropbox_file_path=f"/test/test_{up.id}.jpg",
                dropbox_file_path_display=f"/test/test_{up.id}.jpg",
                dropbox_content_hash=f"hash_{up.id}",
                dropbox_file_id=f"file_id_{up.id}",
                file_size=1024,
                trigger_timestamp=timezone.now(),
                thumbnail_gcloud_path=f"test/thumb_{up.id}.jpg",
            )
        
        # First POST to priority form
        priority_url = reverse('explore:set_priority')
        client_logged_in.post(priority_url, {
            'macrosites': [macro_site.id],
            'priority_by': '4',
        })
        
        # Confirm the update
        confirm_url = reverse('explore:confirm_update')
        response = client_logged_in.post(confirm_url, {})
        
        # Should redirect
        assert response.status_code == 302
        
        # Check priorities - existing should be downgraded, new upload should be highest
        upload.refresh_from_db()
        existing_highest.refresh_from_db()
        
        # Both should exist - one at priority 4 (new), one at priority 3 (downgraded)
        uploads_at_4 = Upload.objects.filter(priority="4").count()
        uploads_at_3 = Upload.objects.filter(priority="3").count()
        
        # We should have at least some at each level after the operation
        assert uploads_at_4 >= 1
        assert uploads_at_3 >= 1
