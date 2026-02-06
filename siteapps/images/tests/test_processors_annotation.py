"""
Tests for images annotation processor functions.
"""
import pytest
from unittest.mock import Mock, patch
from django.conf import settings
from django.utils import timezone

from images.models import (
    Activity, ActivityType, Annotator, Bot, BoundingBox, Category, 
    Image, Species, SpeciesName, Upload
)
from images.processors.annotation import (
    flatten_annotorious_annotations,
    vote,
    set_image_checked_by,
    set_image_skipped_by,
    create_category,
    MAX_VOTES_PER_IMAGE,
    VOTE_THRESHOLD,
    OBJECT_ANNOTATION_TYPE,
    SPECIES_ANNOTATION_TYPE,
    ACTIVITY_ANNOTATION_TYPE,
    UNKNOWN_CATEGORY,
    PERSON_CATEGORY,
    ANIMAL_CATEGORY,
    VEHICLE_CATEGORY,
)
from locations.models import Area, County, MacroSite, MicroSite, CameraStation
from users.models import User


# Fixtures
@pytest.fixture
def area(db):
    """Create an area for testing."""
    return Area.objects.create(name="Test Area")


@pytest.fixture
def county(db, area):
    """Create a county for testing."""
    return County.objects.create(name="Test County", area=area)


@pytest.fixture
def macro_site(db, county):
    """Create a macro site for testing."""
    return MacroSite.objects.create(name="Test Macro Site", county=county)


@pytest.fixture
def micro_site(db, macro_site):
    """Create a micro site for testing."""
    return MicroSite.objects.create(name="Test Micro Site", macro_site=macro_site)


@pytest.fixture
def camera_station(db, micro_site):
    """Create a camera station for testing."""
    return CameraStation.objects.create(
        station_id="TEST001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=90.5,
        date_deployed=timezone.now().date(),
    )


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass",
    )


@pytest.fixture
def camera_station_action(db):
    """Create a camera station action for testing."""
    from images.models import CameraStationAction
    return CameraStationAction.objects.create(action="Retrieved SD card")


@pytest.fixture
def upload(db, camera_station, regular_user, camera_station_action):
    """Create an upload for testing."""
    return Upload.objects.create(
        camera_station=camera_station,
        date_retrieved=timezone.now(),
        last_action=camera_station_action,
        volunteer=regular_user,
        dropbox_folder_name="test_folder",
        dropbox_folder_path="/test/path",
        dropbox_request_id="test123",
        dropbox_request_url="https://dropbox.com/test",
    )


@pytest.fixture
def image(db, upload):
    """Create an image for testing."""
    return Image.objects.create(
        upload=upload,
        dropbox_file_name="test.jpg",
        dropbox_file_path="/test/path/test.jpg",
        dropbox_file_path_display="/test/path/test.jpg",
        dropbox_content_hash="abc123",
        dropbox_file_id="file_id_123",
        file_size=1024,
        processed=True,
    )


@pytest.fixture
def bot(db):
    """Create a bot for testing."""
    return Bot.objects.create(name="MegaDetector", version="v5.0")


@pytest.fixture
def ml_annotator(db, bot):
    """Create an ML annotator for testing."""
    return Annotator.objects.create(type="bot", bot=bot)


@pytest.fixture
def human_annotator(db, regular_user):
    """Create a human annotator for testing."""
    annotator, _ = Annotator.objects.get_or_create(type="human", human=regular_user)
    return annotator


@pytest.mark.django_db
class TestFlattenAnnotoriousAnnotations:
    """Test the flatten_annotorious_annotations function."""
    
    def test_flatten_single_annotation(self):
        """Test flattening a single annotorious annotation."""
        annotations = [{
            "id": "#abc123",
            "target": {
                "selector": {
                    "value": "xywh=pixel:1000,2000,3000,4000"
                }
            },
            "body": [{
                "value": "animal",
                "confidence": 0.95
            }]
        }]
        
        result = flatten_annotorious_annotations(annotations)
        assert "abc123" in result
        assert result["abc123"]["category"] == "animal"
        assert result["abc123"]["confidence"] == 0.95
        assert result["abc123"]["x"] == 10.0
        assert result["abc123"]["y"] == 20.0
        assert result["abc123"]["w"] == 30.0
        assert result["abc123"]["h"] == 40.0
        
    def test_flatten_multiple_annotations(self):
        """Test flattening multiple annotations."""
        annotations = [
            {
                "id": "#box1",
                "target": {"selector": {"value": "xywh=pixel:100,200,300,400"}},
                "body": [{"value": "person", "confidence": 0.85}]
            },
            {
                "id": "#box2",
                "target": {"selector": {"value": "xywh=pixel:500,600,700,800"}},
                "body": [{"value": "vehicle", "confidence": 0.90}]
            }
        ]
        
        result = flatten_annotorious_annotations(annotations)
        assert len(result) == 2
        assert "box1" in result
        assert "box2" in result
        assert result["box1"]["category"] == "person"
        assert result["box2"]["category"] == "vehicle"
        
    def test_flatten_annotation_without_confidence(self):
        """Test annotation without confidence field."""
        annotations = [{
            "id": "#noconf",
            "target": {"selector": {"value": "xywh=pixel:100,200,300,400"}},
            "body": [{"value": "animal"}]
        }]
        
        result = flatten_annotorious_annotations(annotations)
        assert result["noconf"]["confidence"] is None
        
    def test_flatten_annotation_without_category(self):
        """Test annotation without category field."""
        annotations = [{
            "id": "#nocat",
            "target": {"selector": {"value": "xywh=pixel:100,200,300,400"}},
            "body": [{"confidence": 0.75}]
        }]
        
        result = flatten_annotorious_annotations(annotations)
        assert result["nocat"]["category"] is None


@pytest.mark.django_db
class TestVoteFunction:
    """Test the vote function."""
    
    def test_vote_accept(self, image, ml_annotator, human_annotator):
        """Test accepting an annotation."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        vote(bbox, human_annotator, accept=True)
        assert human_annotator in bbox.accepted_by.all()
        assert human_annotator not in bbox.rejected_by.all()
        
    def test_vote_reject(self, image, ml_annotator, human_annotator):
        """Test rejecting an annotation."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        vote(bbox, human_annotator, accept=False)
        assert human_annotator in bbox.rejected_by.all()
        assert human_annotator not in bbox.accepted_by.all()
        
    def test_vote_changes_from_accept_to_reject(self, image, ml_annotator, human_annotator):
        """Test changing vote from accept to reject."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        # First accept
        vote(bbox, human_annotator, accept=True)
        assert human_annotator in bbox.accepted_by.all()
        
        # Then reject
        vote(bbox, human_annotator, accept=False)
        assert human_annotator not in bbox.accepted_by.all()
        assert human_annotator in bbox.rejected_by.all()
        
    def test_vote_reject_by_creator_with_no_other_accepts(self, image, human_annotator):
        """Test that rejecting by creator deletes annotation if no other accepts."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=human_annotator,
        )
        bbox_id = bbox.id
        
        # Creator rejects own annotation with no other accepts
        vote(bbox, human_annotator, accept=False)
        
        # Should be deleted
        assert not BoundingBox.objects.filter(id=bbox_id).exists()
        
    def test_vote_reject_by_creator_with_other_accepts(self, image, human_annotator):
        """Test that rejecting by creator reassigns if others accepted."""
        from users.models import User
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass"
        )
        other_annotator, _ = Annotator.objects.get_or_create(
            type="human",
            human=other_user
        )
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=human_annotator,
        )
        
        # Another annotator accepts
        bbox.accepted_by.add(other_annotator)
        
        # Creator rejects
        vote(bbox, human_annotator, accept=False)
        
        # Should still exist with new creator
        bbox.refresh_from_db()
        assert bbox.created_by == other_annotator
        assert other_annotator not in bbox.accepted_by.all()


@pytest.mark.django_db
class TestSetImageCheckedBy:
    """Test set_image_checked_by function."""
    
    def test_species_checked_by(self, image, human_annotator):
        """Test adding annotator to species_checked_by."""
        set_image_checked_by(SPECIES_ANNOTATION_TYPE, image, human_annotator)
        assert human_annotator in image.species_checked_by.all()
        
    def test_activity_checked_by(self, image, human_annotator):
        """Test adding annotator to activity_checked_by."""
        set_image_checked_by(ACTIVITY_ANNOTATION_TYPE, image, human_annotator)
        assert human_annotator in image.activity_checked_by.all()
        
    def test_unknown_annotation_type(self, image, human_annotator):
        """Test with unknown annotation type - should not crash."""
        set_image_checked_by("UNKNOWN", image, human_annotator)
        # Should not add to any list
        assert human_annotator not in image.species_checked_by.all()
        assert human_annotator not in image.activity_checked_by.all()


@pytest.mark.django_db
class TestSetImageSkippedBy:
    """Test set_image_skipped_by function."""
    
    def test_species_skipped_by(self, image, human_annotator):
        """Test adding annotator to species_skipped_by."""
        set_image_skipped_by(SPECIES_ANNOTATION_TYPE, image, human_annotator)
        assert human_annotator in image.species_skipped_by.all()
        
    def test_activity_skipped_by(self, image, human_annotator):
        """Test adding annotator to activity_skipped_by."""
        set_image_skipped_by(ACTIVITY_ANNOTATION_TYPE, image, human_annotator)
        assert human_annotator in image.activity_skipped_by.all()
        
    def test_unknown_annotation_type(self, image, human_annotator):
        """Test with unknown annotation type - should not crash."""
        set_image_skipped_by("UNKNOWN", image, human_annotator)
        # Should not add to any list
        assert human_annotator not in image.species_skipped_by.all()
        assert human_annotator not in image.activity_skipped_by.all()


@pytest.mark.django_db
class TestCreateCategory:
    """Test create_category function."""
    
    def test_create_category_basic(self, image, ml_annotator, human_annotator):
        """Test creating a category annotation."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        annotation_dict = {
            "category": "animal",
            "confidence": 0.90
        }
        
        # Function returns None but creates the category
        create_category(annotation_dict, bbox, human_annotator)
        
        # Verify category was created
        category = Category.objects.get(bounding_box=bbox)
        assert category.bounding_box == bbox
        assert category.name == "animal"
        assert category.created_by == human_annotator
        assert category.confidence == 0.90
        
    def test_create_category_with_different_categories(self, image, ml_annotator, human_annotator):
        """Test creating different category types."""
        bbox1 = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.3,
            h=0.3,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        bbox2 = BoundingBox.objects.create(
            image=image,
            x=0.5,
            y=0.5,
            w=0.3,
            h=0.3,
            confidence=0.90,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        # Create person category
        create_category(
            {"category": "person", "confidence": 0.85},
            bbox1,
            human_annotator
        )
        
        # Create vehicle category
        create_category(
            {"category": "vehicle", "confidence": 0.92},
            bbox2,
            human_annotator
        )
        
        assert Category.objects.filter(name="person").exists()
        assert Category.objects.filter(name="vehicle").exists()


@pytest.mark.django_db
class TestCreateSpecies:
    """Test create_species function."""
    
    def test_create_species_basic(self, image, ml_annotator, human_annotator):
        """Test creating a species annotation."""
        from images.processors.annotation import create_species
        
        # Create a species name first
        species_name = SpeciesName.objects.create(
            name="Tiger",
            scientific_name="Panthera tigris",
            species_group="WILD"
        )
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        annotation_dict = {
            "category": "Tiger",
            "confidence": 0.88
        }
        
        create_species(annotation_dict, bbox, human_annotator)
        
        # Verify species was created
        species = Species.objects.get(bounding_box=bbox)
        assert species.name == species_name
        assert species.created_by == human_annotator
        assert species.confidence == 0.88


@pytest.mark.django_db
class TestCreateActivity:
    """Test create_activity function."""
    
    def test_create_activity_basic(self, image, ml_annotator, human_annotator):
        """Test creating an activity annotation."""
        from images.processors.annotation import create_activity
        
        # Create an activity type first
        activity_type = ActivityType.objects.create(
            name="Running",
            category="animal"
        )
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        
        annotation_dict = {
            "category": "Running",
            "confidence": 0.75
        }
        
        create_activity(annotation_dict, bbox, human_annotator)
        
        # Verify activity was created
        activity = Activity.objects.get(bounding_box=bbox)
        assert activity.name == activity_type
        assert activity.created_by == human_annotator
        assert activity.confidence == 0.75


@pytest.mark.django_db
class TestCreateBbox:
    """Test create_bbox function."""
    
    def test_create_bbox_with_object_annotation(self, image, human_annotator):
        """Test creating bounding box with object annotation."""
        from images.processors.annotation import create_bbox
        
        annotation_dict = {
            "category": "animal",
            "confidence": 0.90,
            "x": 0.2,
            "y": 0.3,
            "w": 0.4,
            "h": 0.5
        }
        
        bbox = create_bbox(
            OBJECT_ANNOTATION_TYPE,
            annotation_dict,
            image,
            human_annotator
        )
        
        assert bbox is not None
        assert bbox.x == 0.2
        assert bbox.y == 0.3
        assert bbox.w == 0.4
        assert bbox.h == 0.5
        assert bbox.confidence == 0.90
        assert bbox.created_by == human_annotator
        
        # Verify category was also created
        assert Category.objects.filter(bounding_box=bbox).exists()
        
    def test_create_bbox_with_species_annotation(self, image, human_annotator):
        """Test creating bounding box with species annotation."""
        from images.processors.annotation import create_bbox
        
        # Create species name
        SpeciesName.objects.create(
            name="Leopard",
            scientific_name="Panthera pardus",
            species_group="WILD"
        )
        
        annotation_dict = {
            "category": "Leopard",
            "confidence": 0.85,
            "x": 0.1,
            "y": 0.2,
            "w": 0.3,
            "h": 0.4
        }
        
        bbox = create_bbox(
            SPECIES_ANNOTATION_TYPE,
            annotation_dict,
            image,
            human_annotator
        )
        
        assert bbox is not None
        # Verify species was created
        assert Species.objects.filter(bounding_box=bbox).exists()
        
    def test_create_bbox_with_activity_annotation(self, image, human_annotator):
        """Test creating bounding box with activity annotation."""
        from images.processors.annotation import create_bbox
        
        # Create activity type
        ActivityType.objects.create(
            name="Hunting",
            category="animal"
        )
        
        annotation_dict = {
            "category": "Hunting",
            "confidence": 0.80,
            "x": 0.15,
            "y": 0.25,
            "w": 0.35,
            "h": 0.45
        }
        
        bbox = create_bbox(
            ACTIVITY_ANNOTATION_TYPE,
            annotation_dict,
            image,
            human_annotator
        )
        
        assert bbox is not None
        # Verify activity was created
        assert Activity.objects.filter(bounding_box=bbox).exists()


@pytest.mark.django_db  
class TestAnnotationConstants:
    """Test that annotation constants are properly defined."""
    
    def test_max_votes_per_image(self):
        """Test MAX_VOTES_PER_IMAGE constant."""
        assert MAX_VOTES_PER_IMAGE == 2
        
    def test_vote_threshold(self):
        """Test VOTE_THRESHOLD constant."""
        assert VOTE_THRESHOLD == 1
        
    def test_annotation_types(self):
        """Test annotation type constants."""
        assert OBJECT_ANNOTATION_TYPE == "OBJECT"
        assert SPECIES_ANNOTATION_TYPE == "SPECIES"
        assert ACTIVITY_ANNOTATION_TYPE == "ACTIVITY"
        
    def test_category_constants(self):
        """Test category constants."""
        assert UNKNOWN_CATEGORY == "unknown"
        assert PERSON_CATEGORY == "person"
        assert ANIMAL_CATEGORY == "animal"
        assert VEHICLE_CATEGORY == "vehicle"
