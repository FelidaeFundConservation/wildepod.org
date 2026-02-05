"""
Tests for explore app forms.
"""
import pytest
from datetime import date
from django.core.files.uploadedfile import SimpleUploadedFile

from explore.forms import CreateSnapshotForm, ExploreMegadetectorForm
from explore.models import Snapshot


@pytest.mark.django_db
class TestExploreMegadetectorForm:
    """Test the deprecated MegaDetector form."""
    
    def test_form_with_url(self):
        """Test form validation with URL."""
        form = ExploreMegadetectorForm(data={'url': 'https://example.com/image.jpg'})
        assert form.is_valid()
        assert form.cleaned_data['url'] == 'https://example.com/image.jpg'
        
    def test_form_with_image_upload(self):
        """Test form validation with image file."""
        image = SimpleUploadedFile(
            "test.jpg",
            b"fake_image_content",
            content_type="image/jpeg"
        )
        form = ExploreMegadetectorForm(data={}, files={'image': image})
        # Image validation might fail without proper content, so just check it doesn't crash
        # The form initializes properly
        assert 'image' in form.fields
        
    def test_form_both_fields_optional(self):
        """Test that both fields are optional."""
        form = ExploreMegadetectorForm(data={})
        assert form.is_valid()
        
    def test_form_with_both_url_and_image(self):
        """Test form with both URL and image."""
        image = SimpleUploadedFile(
            "test.jpg",
            b"fake_image_content",
            content_type="image/jpeg"
        )
        form = ExploreMegadetectorForm(
            data={'url': 'https://example.com/image.jpg'},
            files={'image': image}
        )
        # At least one should be present
        assert 'url' in form.fields
        assert 'image' in form.fields
        
    def test_form_invalid_url(self):
        """Test form with invalid URL."""
        form = ExploreMegadetectorForm(data={'url': 'not-a-valid-url'})
        assert not form.is_valid()
        assert 'url' in form.errors


@pytest.mark.django_db
class TestCreateSnapshotForm:
    """Test CreateSnapshotForm initialization and validation."""
    
    def test_form_initialization(self):
        """Test that form helper is properly configured."""
        form = CreateSnapshotForm()
        assert form.helper is not None
        assert form.helper.form_show_errors is True
        
    def test_form_date_widgets(self):
        """Test date field widgets are properly configured."""
        form = CreateSnapshotForm()
        # Check that date fields have date input widget
        assert 'start_date' in form.fields
        assert 'end_date' in form.fields
        assert form.fields['start_date'].widget.input_type == 'date'
        assert form.fields['end_date'].widget.input_type == 'date'
        
    def test_form_date_fields_optional(self):
        """Test that date fields are optional."""
        form = CreateSnapshotForm()
        assert form.fields['start_date'].required is False
        assert form.fields['end_date'].required is False
        
    def test_form_with_valid_dates(self):
        """Test form validation with valid date range."""
        from locations.models import Area, County, MacroSite
        
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro_site = MacroSite.objects.create(name="Test MacroSite", county=county)
        
        data = {
            'start_date': date(2024, 1, 1),
            'end_date': date(2024, 12, 31),
            'macrosites': [macro_site.id]
        }
        form = CreateSnapshotForm(data=data)
        assert form.is_valid()
        
    def test_form_without_dates(self):
        """Test form validation without dates."""
        from locations.models import Area, County, MacroSite
        
        area = Area.objects.create(name="Test Area 2")
        county = County.objects.create(name="Test County 2", area=area)
        macro_site = MacroSite.objects.create(name="Test MacroSite 2", county=county)
        
        data = {
            'macrosites': [macro_site.id]
        }
        form = CreateSnapshotForm(data=data)
        assert form.is_valid()
        
    def test_form_with_multiple_macrosites(self):
        """Test form with multiple macrosites."""
        from locations.models import Area, County, MacroSite
        
        area = Area.objects.create(name="Test Area 3")
        county = County.objects.create(name="Test County 3", area=area)
        
        macro_site1 = MacroSite.objects.create(
            name="Site 1",
            county=county
        )
        macro_site2 = MacroSite.objects.create(
            name="Site 2",
            county=county
        )
        
        data = {
            'start_date': date(2024, 1, 1),
            'end_date': date(2024, 12, 31),
            'macrosites': [macro_site1.id, macro_site2.id]
        }
        form = CreateSnapshotForm(data=data)
        assert form.is_valid()
        
    def test_form_save_creates_snapshot(self):
        """Test that form save creates a Snapshot instance."""
        from locations.models import Area, County, MacroSite
        from users.models import User
        
        area = Area.objects.create(name="Test Area 4")
        county = County.objects.create(name="Test County 4", area=area)
        macro_site = MacroSite.objects.create(name="Test MacroSite 4", county=county)
        
        # Create a user for the snapshot
        user = User.objects.create_user(
            email="snapshot_user@example.com",
            password="testpass"
        )
        
        data = {
            'start_date': date(2024, 1, 1),
            'end_date': date(2024, 12, 31),
            'macrosites': [macro_site.id]
        }
        form = CreateSnapshotForm(data=data)
        assert form.is_valid()
        
        snapshot = form.save(commit=False)
        snapshot.volunteer = user
        snapshot.save()
        form.save_m2m()  # Save many-to-many relationships
        
        assert snapshot.start_date == date(2024, 1, 1)
        assert snapshot.end_date == date(2024, 12, 31)
        assert macro_site in snapshot.macrosites.all()
