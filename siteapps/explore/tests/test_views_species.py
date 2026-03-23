"""
Tests for explore/views/species.py
"""
import pytest
from datetime import date
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from images.models import (
    Annotator, BoundingBox, Image, Upload,
    CameraStationAction, SpeciesName, Species, Bot
)
from locations.models import Area, County, MacroSite, MicroSite, CameraStation
from explore.views.species import (
    _build_filter_clauses, _get_base_joins, ts_by_species,
    count_species_sightings, get_images_by
)

User = get_user_model()


@pytest.fixture
def species_setup(db):
    """Create full data structure for species testing."""
    # Create locations
    area = Area.objects.create(name="Test Area Species")
    county = County.objects.create(name="Test County", area=area)
    macro_site = MacroSite.objects.create(name="Test Macro Species", county=county)
    micro_site = MicroSite.objects.create(name="Test Micro Species", macro_site=macro_site)
    station = CameraStation.objects.create(
        station_id="CAM-SPECIES-001",
        latitude=45.0,
        longitude=-100.0,
        micro_site=micro_site,
        date_deployed=timezone.now().date()
    )
    
    # Create user and upload
    user = User.objects.create_user(
        email="species@example.com",
        password="testpass",
        name="Species Tester"
    )
    action = CameraStationAction.objects.create(action="SPECIES_TEST")
    upload = Upload.objects.create(
        camera_station=station,
        date_retrieved=timezone.now(),
        last_action=action,
        volunteer=user,
        dropbox_folder_name="species_folder",
        dropbox_folder_path="/test/species",
        dropbox_request_id="req_species",
        dropbox_request_url="https://dropbox.com/species"
    )
    
    # Create annotator
    bot = Bot.objects.create(name="SpeciesBot", version="v1.0")
    annotator = Annotator.objects.create(type="bot", bot=bot)
    
    # Create species name
    species_name = SpeciesName.objects.create(
        name="Tiger",
        scientific_name="Panthera tigris"
    )
    
    return {
        'macro_site': macro_site,
        'micro_site': micro_site,
        'station': station,
        'upload': upload,
        'annotator': annotator,
        'species_name': species_name,
        'user': user
    }


@pytest.fixture
def create_species_image(species_setup):
    """Factory function to create images with species annotations."""
    counter = {'count': 0}
    
    def _create(trigger_date=None, species_name=None):
        if trigger_date is None:
            trigger_date = timezone.now()
        if species_name is None:
            species_name = species_setup['species_name']
        
        counter['count'] += 1
        num = counter['count']
            
        image = Image.objects.create(
            upload=species_setup['upload'],
            dropbox_file_name=f"tiger_{num}.jpg",
            dropbox_file_path=f"/test/tiger_{num}.jpg",
            dropbox_file_path_display=f"/test/tiger_{num}.jpg",
            dropbox_content_hash=f"hash_tiger_{num}",
            dropbox_file_id=f"file_tiger_{num}",
            file_size=1024,
            trigger_timestamp=trigger_date,
            thumbnail_gcloud_path=f"test/tiger_{num}.jpg"
        )
        
        # Create bounding box directly linking to image
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=species_setup['annotator']
        )
        
        # Create species annotation
        species = Species.objects.create(
            bounding_box=bbox,
            name=species_name,
            confidence=0.95,
            created_by=species_setup['annotator']
        )
        
        return image, species
    
    return _create


@pytest.mark.django_db
class TestHelperFunctions:
    """Test helper functions for building SQL queries."""
    
    def test_build_filter_clauses_with_all_filters(self):
        """Test _build_filter_clauses with all filters provided."""
        macro, micro, station = _build_filter_clauses(
            macrosite="TestMacro",
            microsite="TestMicro",
            station="CAM-001"
        )
        
        assert "location_macro.name = 'TestMacro'" in macro
        assert "location_micro.name = 'TestMicro'" in micro
        assert "location_camera.station_id = 'CAM-001'" in station
    
    def test_build_filter_clauses_with_no_filters(self):
        """Test _build_filter_clauses with no filters (should return tautologies)."""
        macro, micro, station = _build_filter_clauses()
        
        assert "location_macro.name = location_macro.name" in macro
        assert "location_micro.name = location_micro.name" in micro
        assert "location_camera.station_id = location_camera.station_id" in station
    
    def test_build_filter_clauses_with_partial_filters(self):
        """Test _build_filter_clauses with some filters."""
        macro, micro, station = _build_filter_clauses(macrosite="TestMacro")
        
        assert "location_macro.name = 'TestMacro'" in macro
        assert "location_micro.name = location_micro.name" in micro
        assert "location_camera.station_id = location_camera.station_id" in station
    
    def test_get_base_joins_returns_both_formats(self):
        """Test _get_base_joins returns both SQLite and PostgreSQL formats."""
        sqlite_joins, postgres_joins = _get_base_joins()
        
        assert "LEFT JOIN images_species" in sqlite_joins
        assert "RIGHT JOIN images_speciesname" in postgres_joins
        assert "INNER JOIN images_annotator" in sqlite_joins
        assert "INNER JOIN images_annotator" in postgres_joins


@pytest.mark.django_db
class TestTsBySpecies:
    """Test ts_by_species function."""
    
    def test_ts_by_species_basic(self, species_setup, create_species_image):
        """Test basic species timeseries query."""
        # Create an image with species
        create_species_image(trigger_date=timezone.now())
        
        # Query species timeseries
        results = ts_by_species(species="Tiger")
        results_list = list(results)
        
        # Should have at least one result
        assert len(results_list) >= 1
    
    def test_ts_by_species_with_macrosite_filter(self, species_setup, create_species_image):
        """Test timeseries with macrosite filter."""
        create_species_image()
        
        results = ts_by_species(
            species="Tiger",
            macrosite="Test Macro Species"
        )
        results_list = list(results)
        
        assert len(results_list) >= 1
    
    def test_ts_by_species_with_all_filters(self, species_setup, create_species_image):
        """Test timeseries with all location filters."""
        create_species_image()
        
        results = ts_by_species(
            species="Tiger",
            macrosite="Test Macro Species",
            microsite="Test Micro Species",
            station="CAM-SPECIES-001"
        )
        results_list = list(results)
        
        assert len(results_list) >= 1
    
    def test_ts_by_species_with_sorting(self, species_setup, create_species_image):
        """Test timeseries with sorting parameters."""
        # Create multiple images at different times
        from datetime import timedelta
        now = timezone.now()
        create_species_image(trigger_date=now - timedelta(days=2))
        create_species_image(trigger_date=now - timedelta(days=1))
        
        # Sort by exif_dt ascending
        results = ts_by_species(
            species="Tiger",
            sort_by="exif_dt",
            sort_dir="asc"
        )
        results_list = list(results)
        
        assert len(results_list) >= 2
    
    def test_ts_by_species_with_pagination(self, species_setup, create_species_image):
        """Test timeseries with LIMIT and OFFSET."""
        # Create multiple images
        for i in range(3):
            create_species_image(trigger_date=timezone.now())
        
        # Get first page (limit 2)
        results = ts_by_species(
            species="Tiger",
            limit=2,
            offset=0
        )
        results_list = list(results)
        
        assert len(results_list) <= 2
    
    def test_ts_by_species_with_invalid_sort(self, species_setup, create_species_image):
        """Test timeseries with invalid sort parameter - should use default."""
        create_species_image()
        
        # Invalid sort_by should default to exif_dt desc
        results = ts_by_species(
            species="Tiger",
            sort_by="invalid_column",
            sort_dir="asc"
        )
        results_list = list(results)
        
        # Should still work with default sorting
        assert len(results_list) >= 1


@pytest.mark.django_db
class TestCountSpeciesSightings:
    """Test count_species_sightings function."""
    
    def test_count_species_sightings_basic(self, species_setup, create_species_image):
        """Test basic count query."""
        create_species_image()
        
        count = count_species_sightings(species="Tiger")
        
        assert count >= 1
    
    def test_count_species_sightings_with_filters(self, species_setup, create_species_image):
        """Test count with location filters."""
        create_species_image()
        
        count = count_species_sightings(
            species="Tiger",
            macrosite="Test Macro Species",
            microsite="Test Micro Species"
        )
        
        assert count >= 1
    
    def test_count_species_sightings_no_results(self, species_setup):
        """Test count when no species found."""
        count = count_species_sightings(species="Nonexistent Species")
        
        assert count == 0


@pytest.mark.django_db
class TestGetImagesBy:
    """Test get_images_by function."""
    
    def test_get_images_by_basic(self, species_setup, create_species_image):
        """Test getting images for a species on a specific date."""
        trigger_date = date(2026, 3, 20)
        trigger_datetime = timezone.make_aware(
            timezone.datetime.combine(trigger_date, timezone.datetime.min.time())
        )
        create_species_image(trigger_date=trigger_datetime)
        
        images = get_images_by(
            species="Tiger",
            date_sighting="2026-03-20",
            macrosite="Test Macro Species",
            microsite="Test Micro Species"
        )
        images_list = list(images)
        
        assert len(images_list) >= 1
    
    def test_get_images_by_with_special_chars_in_microsite(self, species_setup, create_species_image):
        """Test get_images_by with microsite name containing special characters."""
        # Create a micro site with single quote
        micro_special = MicroSite.objects.create(
            name="Test's Micro",
            macro_site=species_setup['macro_site']
        )
        
        station_special = CameraStation.objects.create(
            station_id="CAM-SPECIAL-001",
            latitude=45.5,
            longitude=-100.5,
            micro_site=micro_special,
            date_deployed=timezone.now().date()
        )
        
        # Create upload for this station
        upload_special = Upload.objects.create(
            camera_station=station_special,
            date_retrieved=timezone.now(),
            last_action=species_setup['upload'].last_action,
            volunteer=species_setup['user'],
            dropbox_folder_name="special_folder",
            dropbox_folder_path="/test/special",
            dropbox_request_id="req_special",
            dropbox_request_url="https://dropbox.com/special"
        )
        
        # Create image for this upload
        trigger_date = date(2026, 3, 20)
        trigger_datetime = timezone.make_aware(
            timezone.datetime.combine(trigger_date, timezone.datetime.min.time())
        )
        image = Image.objects.create(
            upload=upload_special,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/test.jpg",
            dropbox_file_path_display="/test/test.jpg",
            dropbox_content_hash="hash",
            dropbox_file_id="file",
            file_size=1024,
            trigger_timestamp=trigger_datetime,
            thumbnail_gcloud_path="test/test.jpg"
        )
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            created_by=species_setup['annotator']
        )
        
        Species.objects.create(
            bounding_box=bbox,
            name=species_setup['species_name'],
            confidence=0.95,
            created_by=species_setup['annotator']
        )
        
        # Query should handle single quote correctly
        images = get_images_by(
            species="Tiger",
            date_sighting="2026-03-20",
            macrosite="Test Macro Species",
            microsite="Test's Micro"
        )
        images_list = list(images)
        
        assert len(images_list) >= 1


@pytest.mark.django_db
class TestSpeciesSightingTimeseriesView:
    """Test SpeciesSightingTimeseriesView."""
    
    @pytest.fixture
    def client_logged_in(self, client, species_setup):
        """Return logged-in client."""
        client.force_login(species_setup['user'])
        return client
    
    def test_get_requires_login(self, client):
        """Test GET requires authentication."""
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client.get(url)
        
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_get_with_logged_in_user(self, client_logged_in, species_setup):
        """Test GET with logged-in user."""
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'species' in response.context
        assert response.context['species'] == 'Tiger'
    
    def test_get_with_species_data(self, client_logged_in, species_setup, create_species_image):
        """Test GET displays species sighting data."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url)
        
        assert response.status_code == 200
        assert 'species_sighting_timeserie_list' in response.context
        assert 'species_l' in response.context
    
    def test_get_with_per_page_parameter(self, client_logged_in, species_setup, create_species_image):
        """Test GET with per_page parameter."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'per_page': '10'})
        
        assert response.status_code == 200
        assert response.context['per_page'] == '10'
    
    def test_get_with_per_page_all(self, client_logged_in, species_setup, create_species_image):
        """Test GET with per_page=all disables pagination."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'per_page': 'all'})
        
        assert response.status_code == 200
        assert response.context['is_paginated'] is False
    
    def test_get_with_invalid_per_page(self, client_logged_in, species_setup, create_species_image):
        """Test GET with invalid per_page defaults to 25."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'per_page': 'invalid'})
        
        assert response.status_code == 200
        # Should use default of 25
    
    def test_get_with_macrosite_filter(self, client_logged_in, species_setup, create_species_image):
        """Test GET with macrosite filter."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'macrosite': 'Test Macro Species'})
        
        assert response.status_code == 200
    
    def test_get_with_sorting(self, client_logged_in, species_setup, create_species_image):
        """Test GET with sort and dir parameters."""
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'sort': 'total', 'dir': 'asc'})
        
        assert response.status_code == 200
        assert response.context['current_sort'] == 'total'
        assert response.context['current_dir'] == 'asc'
    
    def test_get_with_pagination(self, client_logged_in, species_setup, create_species_image):
        """Test GET with page parameter."""
        # Create multiple sightings
        for i in range(3):
            create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'page': '1', 'per_page': '25'})
        
        assert response.status_code == 200
        assert 'page_obj' in response.context
    
    def test_get_pagination_creates_page_range(self, client_logged_in, species_setup, create_species_image):
        """Test pagination creates elided page range for many results."""
        # This would need many images to trigger elided range
        create_species_image()
        
        url = reverse('explore:species_sighting_timeserie_list', kwargs={'species': 'Tiger'})
        response = client_logged_in.get(url, {'per_page': '1'})
        
        assert response.status_code == 200
        # With pagination enabled, page_range should be in context
        if response.context.get('is_paginated'):
            assert 'page_range' in response.context


@pytest.mark.django_db
class TestSpeciesSightingImagesView:
    """Test SpeciesSightingImagesView."""
    
    @pytest.fixture
    def client_logged_in(self, client, species_setup):
        """Return logged-in client."""
        client.force_login(species_setup['user'])
        return client
    
    def test_get_requires_login(self, client):
        """Test GET requires authentication."""
        url = reverse('explore:species_sighting_images')
        response = client.get(url)
        
        assert response.status_code == 302
        assert '/login/' in response.url
    
    def test_get_with_logged_in_user(self, client_logged_in, species_setup):
        """Test GET with logged-in user."""
        url = reverse('explore:species_sighting_images')
        response = client_logged_in.get(url, {
            'species': 'Tiger',
            'macrosite': 'Test Macro Species',
            'microsite': 'Test Micro Species',
            'date_sighting': '2026-03-20'
        })
        
        assert response.status_code == 200
        assert 'images_list' in response.context
        assert response.context['species'] == 'Tiger'
    
    def test_get_displays_images(self, client_logged_in, species_setup, create_species_image):
        """Test GET displays images for a species sighting."""
        trigger_date = date(2026, 3, 20)
        trigger_datetime = timezone.make_aware(
            timezone.datetime.combine(trigger_date, timezone.datetime.min.time())
        )
        create_species_image(trigger_date=trigger_datetime)
        
        url = reverse('explore:species_sighting_images')
        response = client_logged_in.get(url, {
            'species': 'Tiger',
            'macrosite': 'Test Macro Species',
            'microsite': 'Test Micro Species',
            'date_sighting': '2026-03-20'
        })
        
        assert response.status_code == 200
        assert 'images_list' in response.context
        assert response.context['macrosite'] == 'Test Macro Species'
        assert response.context['microsite'] == 'Test Micro Species'
        assert response.context['date_sighting'] == '2026-03-20'
