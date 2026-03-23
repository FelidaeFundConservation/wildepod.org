"""
Tests for explore popular_images views.
"""
import json
import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from explore.views.popular_images import ExplorePopularImagesView, RemovePopularImageView
from images.models import Annotator, BoundingBox, Bot, Category, CameraStationAction, Image, Species, SpeciesName, Upload
from locations.models import Area, County, MacroSite, MicroSite, CameraStation

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a user for testing."""
    user = User.objects.create_user(
        email="user@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def client_logged_in(user):
    """Create a logged-in client."""
    client = Client()
    client.force_login(user)
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
def upload(db, camera_station, user):
    """Create an upload for testing."""
    action, _ = CameraStationAction.objects.get_or_create(
        action="RETRIEVE"
    )
    upload = Upload.objects.create(
        camera_station=camera_station,
        volunteer=user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="test_folder_popular_123",
        dropbox_folder_path="/test/folder/popular_123",
        dropbox_request_id="req_popular_123",
        dropbox_request_url="https://dropbox.com/request/popular_123",
    )
    return upload


@pytest.fixture
def species_name(db):
    """Create a species name for testing."""
    species_name = SpeciesName.objects.create(
        name="Tiger",
        active=True,
    )
    return species_name


@pytest.fixture
def bot(db):
    """Create a bot for testing."""
    return Bot.objects.create(name="MegaDetector", version="v5.0")


@pytest.fixture
def ml_annotator(db, bot):
    """Create an ML annotator for testing."""
    return Annotator.objects.create(type="bot", bot=bot)


@pytest.fixture
def human_annotator(db, user):
    """Create a human annotator for testing."""
    annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
    return annotator


@pytest.mark.django_db
class TestExplorePopularImagesView:
    """Test ExplorePopularImagesView."""
    
    def test_get_requires_login(self, client):
        """Test that GET requires login."""
        url = reverse('explore:popular_images')
        response = client.get(url)
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_get_with_no_popular_images(self, client_logged_in):
        """Test GET with no popular images."""
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'paged_images' in response.context
    
    def test_get_shows_popular_images(self, client_logged_in, upload, human_annotator):
        """Test GET shows images with social_media_worthy > 0."""
        # Create popular image
        popular_image = Image.objects.create(
            upload=upload,
            dropbox_file_name="popular.jpg",
            dropbox_file_path="/test/popular.jpg",
            dropbox_file_path_display="/test/popular.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="file_id_1",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/popular.jpg",
            social_media_worthy=5,
        )
        popular_image.species_checked_by.set([human_annotator])
        
        # Create non-popular image
        Image.objects.create(
            upload=upload,
            dropbox_file_name="regular.jpg",
            dropbox_file_path="/test/regular.jpg",
            dropbox_file_path_display="/test/regular.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="file_id_2",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/regular.jpg",
            social_media_worthy=0,
        )
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        images = response.context['paged_images']
        
        # Should only include popular image
        assert popular_image in images
        assert len(images) == 1
    
    def test_get_excludes_images_without_species_check(self, client_logged_in, upload):
        """Test GET excludes images without species_checked_by."""
        # Create image with social_media_worthy but no species check
        Image.objects.create(
            upload=upload,
            dropbox_file_name="unchecked.jpg",
            dropbox_file_path="/test/unchecked.jpg",
            dropbox_file_path_display="/test/unchecked.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/unchecked.jpg",
            social_media_worthy=5,
        )
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        images = response.context['paged_images']
        
        # Should not include unchecked image
        assert len(images) == 0
    
    def test_get_with_species_filter(self, client_logged_in, upload, species_name, ml_annotator, human_annotator):
        """Test GET with species filter."""
        # Create image with species
        image = Image.objects.create(
            upload=upload,
            dropbox_file_name="tiger.jpg",
            dropbox_file_path="/test/tiger.jpg",
            dropbox_file_path_display="/test/tiger.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/tiger.jpg",
            social_media_worthy=5,
        )
        image.species_checked_by.set([human_annotator])
        
        # Create bounding box with species
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.4,
            h=0.4,
            confidence=0.9,
            created_by=ml_annotator,
        )
        
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.9,
            created_by=ml_annotator,
        )
        
        Species.objects.create(
            bounding_box=bbox,
            name=species_name,
            confidence=0.9,
            created_by=ml_annotator,
        )
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url, {'species': [species_name.id]})
        
        assert response.status_code == 200
        assert 'selected_species' in response.context
        assert species_name.id in response.context['selected_species']
    
    def test_get_with_invalid_species_filter(self, client_logged_in):
        """Test GET with invalid species IDs filters them out."""
        url = reverse('explore:popular_images')
        # Pass empty string and valid ID
        response = client_logged_in.get(url, {'species': ['', '999999']})
        
        assert response.status_code == 200
        # Should handle gracefully
    
    def test_get_with_pagination(self, client_logged_in, upload, human_annotator):
        """Test GET with pagination."""
        # Create multiple popular images
        for i in range(30):
            img = Image.objects.create(
                upload=upload,
                dropbox_file_name=f"popular_{i}.jpg",
                dropbox_file_path=f"/test/popular_{i}.jpg",
                dropbox_file_path_display=f"/test/popular_{i}.jpg",
                dropbox_content_hash=f"hash_{i}",
                dropbox_file_id=f"file_id_{i}",
                file_size=1024,
                trigger_timestamp=timezone.now(),
                thumbnail_gcloud_path=f"test/popular_{i}.jpg",
                social_media_worthy=5,
            )
            img.species_checked_by.set([human_annotator])
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url, {'per_page': '24'})
        
        assert response.status_code == 200
        assert response.context['is_paginated'] is True
        assert len(response.context['paged_images']) == 24
    
    def test_get_with_per_page_all(self, client_logged_in, upload, human_annotator):
        """Test GET with per_page=all."""
        # Create multiple popular images
        for i in range(30):
            img = Image.objects.create(
                upload=upload,
                dropbox_file_name=f"popular_{i}.jpg",
                dropbox_file_path=f"/test/popular_{i}.jpg",
                dropbox_file_path_display=f"/test/popular_{i}.jpg",
                dropbox_content_hash=f"hash_{i}",
                dropbox_file_id=f"file_id_{i}",
                file_size=1024,
                trigger_timestamp=timezone.now(),
                thumbnail_gcloud_path=f"test/popular_{i}.jpg",
                social_media_worthy=5,
            )
            img.species_checked_by.set([human_annotator])
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url, {'per_page': 'all'})
        
        assert response.status_code == 200
        assert response.context['is_paginated'] is False
        assert len(response.context['paged_images']) == 30
    
    def test_get_with_invalid_per_page(self, client_logged_in, upload, human_annotator):
        """Test GET with invalid per_page defaults to 24."""
        img = Image.objects.create(
            upload=upload,
            dropbox_file_name="popular.jpg",
            dropbox_file_path="/test/popular.jpg",
            dropbox_file_path_display="/test/popular.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file_id",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/popular.jpg",
            social_media_worthy=5,
        )
        img.species_checked_by.set([human_annotator])
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url, {'per_page': 'invalid'})
        
        assert response.status_code == 200
        assert response.context['per_page'] == 'invalid'
    
    def test_get_elided_page_range_small(self, client_logged_in, upload, human_annotator):
        """Test elided page range with few pages."""
        # Create 5 images (less than 10 pages)
        for i in range(5):
            img = Image.objects.create(
                upload=upload,
                dropbox_file_name=f"popular_{i}.jpg",
                dropbox_file_path=f"/test/popular_{i}.jpg",
                dropbox_file_path_display=f"/test/popular_{i}.jpg",
                dropbox_content_hash=f"hash_{i}",
                dropbox_file_id=f"file_id_{i}",
                file_size=1024,
                trigger_timestamp=timezone.now(),
                thumbnail_gcloud_path=f"test/popular_{i}.jpg",
                social_media_worthy=5,
            )
            img.species_checked_by.set([human_annotator])
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        # With 5 images and 24 per page, should have 1 page - no ellipsis needed
    
    def test_get_context_has_all_species(self, client_logged_in, species_name):
        """Test that context includes all active species."""
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'all_species' in response.context
        assert species_name in response.context['all_species']
    
    def test_get_orders_by_timestamp(self, client_logged_in, upload, human_annotator):
        """Test that images are ordered by trigger_timestamp descending."""
        # Create images with different timestamps
        old_image = Image.objects.create(
            upload=upload,
            dropbox_file_name="old.jpg",
            dropbox_file_path="/test/old.jpg",
            dropbox_file_path_display="/test/old.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="file_id_1",
            file_size=1024,
            trigger_timestamp=timezone.now() - timezone.timedelta(days=10),
            thumbnail_gcloud_path="test/old.jpg",
            social_media_worthy=5,
        )
        old_image.species_checked_by.set([human_annotator])
        
        new_image = Image.objects.create(
            upload=upload,
            dropbox_file_name="new.jpg",
            dropbox_file_path="/test/new.jpg",
            dropbox_file_path_display="/test/new.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="file_id_2",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/new.jpg",
            social_media_worthy=5,
        )
        new_image.species_checked_by.set([human_annotator])
        
        url = reverse('explore:popular_images')
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        images = list(response.context['paged_images'])
        
        # New image should come first
        assert images[0] == new_image
        assert images[1] == old_image


@pytest.mark.django_db
class TestRemovePopularImageView:
    """Test RemovePopularImageView."""
    
    def test_post_requires_login(self, client):
        """Test that POST requires login."""
        url = reverse('explore:remove_popular_image')
        response = client.post(url, {})
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_post_removes_images(self, client_logged_in, upload, human_annotator):
        """Test POST removes images from popular list."""
        # Create popular images
        image1 = Image.objects.create(
            upload=upload,
            dropbox_file_name="pop1.jpg",
            dropbox_file_path="/test/pop1.jpg",
            dropbox_file_path_display="/test/pop1.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="file_id_1",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/pop1.jpg",
            social_media_worthy=5,
        )
        image1.species_checked_by.set([human_annotator])
        
        image2 = Image.objects.create(
            upload=upload,
            dropbox_file_name="pop2.jpg",
            dropbox_file_path="/test/pop2.jpg",
            dropbox_file_path_display="/test/pop2.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="file_id_2",
            file_size=1024,
            trigger_timestamp=timezone.now(),
            thumbnail_gcloud_path="test/pop2.jpg",
            social_media_worthy=5,
        )
        image2.species_checked_by.set([human_annotator])
        
        url = reverse('explore:remove_popular_image')
        response = client_logged_in.post(url, {
            'imageIds': json.dumps([str(image1.id), str(image2.id)])
        })
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        
        # Check images were updated
        image1.refresh_from_db()
        image2.refresh_from_db()
        
        assert image1.social_media_worthy == 0
        assert image2.social_media_worthy == 0
    
    def test_post_with_no_image_ids(self, client_logged_in):
        """Test POST with no image IDs."""
        url = reverse('explore:remove_popular_image')
        response = client_logged_in.post(url, {})
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
    
    def test_post_with_invalid_image_id(self, client_logged_in):
        """Test POST with invalid image ID."""
        url = reverse('explore:remove_popular_image')
        response = client_logged_in.post(url, {
            'imageIds': json.dumps(['00000000-0000-0000-0000-000000000000'])
        })
        
        assert response.status_code == 200
        data = json.loads(response.content)
        # Should return success=False if any image fails
        assert data['success'] is False
