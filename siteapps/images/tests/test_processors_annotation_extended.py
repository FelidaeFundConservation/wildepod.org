"""Extended tests for annotation processors to increase coverage"""
import pytest
from django.contrib.auth import get_user_model
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
)
from images.processors.annotation import (
    ACTIVITY_ANNOTATION_TYPE,
    OBJECT_ANNOTATION_TYPE,
    SPECIES_ANNOTATION_TYPE,
    create_activity,
    create_bbox,
    create_category,
    create_species,
    handle_bbox_additions,
    handle_bbox_deletions,
    handle_bbox_updates,
    set_image_checked_by,
    set_image_skipped_by,
    vote,
)
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def camera_station(db):
    """Create a camera station for testing"""
    from datetime import date

    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    macro_site = MacroSite.objects.create(name="Test Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Test Micro Site", macro_site=macro_site)
    return CameraStation.objects.create(
        station_id="TEST001",
        micro_site=micro_site,
        latitude=40.7128,
        longitude=-74.0060,
        date_deployed=date(2024, 1, 1),
    )


@pytest.fixture
def upload(db, camera_station, user):
    """Create an upload for testing"""
    from datetime import datetime
    from images.models import CameraStationAction
    
    action, _ = CameraStationAction.objects.get_or_create(action="Retrieved SD Card")
    return Upload.objects.create(
        volunteer=user,
        camera_station=camera_station,
        date_retrieved=datetime.now(),
        last_action=action,
    )


@pytest.fixture
def test_image(db, upload):
    """Create an image for testing"""
    return Image.objects.create(
        upload=upload,
        dropbox_file_path="/test/image.jpg",
        dropbox_file_name="image.jpg",
        dropbox_file_path_display="/test/image.jpg",
        dropbox_content_hash="test_hash_123",
        dropbox_file_id="test_file_id_123",
        file_size=1024000,
    )


@pytest.fixture
def human_annotator(db, user):
    """Create a human annotator"""
    annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
    return annotator


@pytest.fixture
def species_name(db):
    """Create a species name for testing"""
    return SpeciesName.objects.create(name="Red Fox", species_group="animal")


@pytest.fixture
def activity_type(db):
    """Create an activity type for testing"""
    return ActivityType.objects.create(name="Walking", category="Moving")


@pytest.mark.django_db
class TestCreateCategory:
    def test_create_category_with_confidence(self, test_image, human_annotator):
        """Test creating a category with confidence value"""
        bbox = BoundingBox.objects.create(
            image=test_image,
            x=0.1,
            y=0.2,
            w=0.3,
            h=0.4,
            created_by=human_annotator,
        )

        annotation_dict = {"category": "animal", "confidence": 0.95}

        create_category(annotation_dict, bbox, human_annotator)

        category = Category.objects.get(bounding_box=bbox)
        assert category.name == "animal"
        assert category.confidence == 0.95
        assert category.created_by == human_annotator

    def test_create_category_vehicle(self, test_image, human_annotator):
        """Test creating a vehicle category"""
        bbox = BoundingBox.objects.create(
            image=test_image,
            x=0.1,
            y=0.2,
            w=0.3,
            h=0.4,
            created_by=human_annotator,
        )

        annotation_dict = {"category": "vehicle", "confidence": 0.88}

        create_category(annotation_dict, bbox, human_annotator)

        category = Category.objects.get(bounding_box=bbox)
        assert category.name == "vehicle"


@pytest.mark.django_db
class TestCreateSpecies:
    def test_create_species_basic(self, test_image, human_annotator, species_name):
        """Test creating a species annotation"""
        bbox = BoundingBox.objects.create(
            image=test_image,
            x=0.15,
            y=0.25,
            w=0.35,
            h=0.45,
            created_by=human_annotator,
        )

        annotation_dict = {"category": "Red Fox", "confidence": 0.92}

        create_species(annotation_dict, bbox, human_annotator)

        species = Species.objects.get(bounding_box=bbox)
        assert species.name.name == "Red Fox"
        assert species.confidence == 0.92
        assert species.created_by == human_annotator


@pytest.mark.django_db
class TestCreateActivity:
    def test_create_activity_basic(self, test_image, human_annotator, activity_type):
        """Test creating an activity annotation"""
        bbox = BoundingBox.objects.create(
            image=test_image,
            x=0.2,
            y=0.3,
            w=0.4,
            h=0.5,
            created_by=human_annotator,
        )

        annotation_dict = {"category": "Walking", "confidence": 0.85}

        create_activity(annotation_dict, bbox, human_annotator)

        activity = Activity.objects.get(bounding_box=bbox)
        assert activity.name.name == "Walking"
        assert activity.confidence == 0.85
        assert activity.created_by == human_annotator


@pytest.mark.django_db
class TestCreateBbox:
    def test_create_bbox_with_object_annotation(self, test_image, human_annotator):
        """Test creating a bounding box with object annotation"""
        annotation_dict = {
            "category": "person",
            "confidence": 0.97,
            "x": 0.1,
            "y": 0.2,
            "w": 0.3,
            "h": 0.4,
        }

        bbox = create_bbox(OBJECT_ANNOTATION_TYPE, annotation_dict, test_image, human_annotator)

        assert bbox.x == 0.1
        assert bbox.y == 0.2
        assert bbox.w == 0.3
        assert bbox.h == 0.4
        assert bbox.confidence == 0.97
        assert Category.objects.filter(bounding_box=bbox).exists()

    def test_create_bbox_with_species_annotation(self, test_image, human_annotator, species_name):
        """Test creating a bounding box with species annotation"""
        annotation_dict = {
            "category": "Red Fox",
            "confidence": 0.89,
            "x": 0.15,
            "y": 0.25,
            "w": 0.35,
            "h": 0.45,
        }

        bbox = create_bbox(SPECIES_ANNOTATION_TYPE, annotation_dict, test_image, human_annotator)

        assert bbox.x == 0.15
        assert Species.objects.filter(bounding_box=bbox).exists()
        # Should also infer and create category based on species_group
        assert Category.objects.filter(bounding_box=bbox).exists()

    def test_create_bbox_with_activity_annotation(self, test_image, human_annotator, activity_type):
        """Test creating a bounding box with activity annotation"""
        annotation_dict = {
            "category": "Walking",
            "confidence": 0.82,
            "x": 0.2,
            "y": 0.3,
            "w": 0.4,
            "h": 0.5,
        }

        bbox = create_bbox(ACTIVITY_ANNOTATION_TYPE, annotation_dict, test_image, human_annotator)

        assert bbox.x == 0.2
        assert Activity.objects.filter(bounding_box=bbox).exists()


@pytest.mark.django_db
class TestVoteFunction:
    def test_vote_accept_adds_to_accepted(self, test_image, human_annotator):
        """Test accepting adds annotator to accepted_by"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )

        # Create another annotator to vote
        other_user = User.objects.create_user(email="voter@test.com")
        voter_annotator, _ = Annotator.objects.get_or_create(type="human", human=other_user)

        vote(bbox, voter_annotator, accept=True)

        assert voter_annotator in bbox.accepted_by.all()
        assert voter_annotator not in bbox.rejected_by.all()

    def test_vote_reject_adds_to_rejected(self, test_image, human_annotator):
        """Test rejecting adds annotator to rejected_by"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )

        other_user = User.objects.create_user(email="voter@test.com")
        voter_annotator, _ = Annotator.objects.get_or_create(type="human", human=other_user)

        vote(bbox, voter_annotator, accept=False)

        assert voter_annotator not in bbox.accepted_by.all()
        assert voter_annotator in bbox.rejected_by.all()

    def test_vote_creator_reject_with_no_accepts_deletes(self, test_image, human_annotator):
        """Test creator rejecting their own annotation with no other accepts deletes it"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )
        bbox_id = bbox.id

        # Creator rejects their own annotation
        vote(bbox, human_annotator, accept=False)

        # Bbox should be deleted
        assert not BoundingBox.objects.filter(id=bbox_id).exists()

    def test_vote_creator_reject_with_accepts_reassigns(self, test_image, human_annotator):
        """Test creator rejecting with other accepts reassigns creator"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )

        # Another user accepts
        other_user = User.objects.create_user(email="acceptor@test.com")
        other_annotator, _ = Annotator.objects.get_or_create(type="human", human=other_user)
        vote(bbox, other_annotator, accept=True)

        # Creator rejects
        vote(bbox, human_annotator, accept=False)

        # Refresh from db
        bbox.refresh_from_db()

        # Created_by should be reassigned to other_annotator
        assert bbox.created_by == other_annotator
        assert human_annotator in bbox.rejected_by.all()


@pytest.mark.django_db
class TestSetImageCheckedBy:
    def test_species_checked_by(self, test_image, human_annotator):
        """Test setting species checked by"""
        set_image_checked_by(SPECIES_ANNOTATION_TYPE, test_image, human_annotator)

        assert human_annotator in test_image.species_checked_by.all()

    def test_activity_checked_by(self, test_image, human_annotator):
        """Test setting activity checked by"""
        set_image_checked_by(ACTIVITY_ANNOTATION_TYPE, test_image, human_annotator)

        assert human_annotator in test_image.activity_checked_by.all()


@pytest.mark.django_db
class TestSetImageSkippedBy:
    def test_species_skipped_by(self, test_image, human_annotator):
        """Test setting species skipped by"""
        set_image_skipped_by(SPECIES_ANNOTATION_TYPE, test_image, human_annotator)

        assert human_annotator in test_image.species_skipped_by.all()

    def test_activity_skipped_by(self, test_image, human_annotator):
        """Test setting activity skipped by"""
        set_image_skipped_by(ACTIVITY_ANNOTATION_TYPE, test_image, human_annotator)

        assert human_annotator in test_image.activity_skipped_by.all()


@pytest.mark.django_db
class TestHandleBboxAdditions:
    def test_handle_bbox_additions_creates_new_bboxes(self, test_image, human_annotator):
        """Test that new bounding boxes are created"""
        initial_bboxes = []
        formatted_annotations = {
            "new-uuid-1": {
                "id": "new-uuid-1",
                "category": "animal",
                "confidence": 0.9,
                "x": 0.1,
                "y": 0.2,
                "w": 0.3,
                "h": 0.4,
            }
        }

        handle_bbox_additions(
            OBJECT_ANNOTATION_TYPE, initial_bboxes, formatted_annotations, test_image, human_annotator
        )

        assert BoundingBox.objects.filter(image=test_image).count() == 1
        bbox = BoundingBox.objects.get(image=test_image)
        assert bbox.x == 0.1

    def test_handle_bbox_additions_multiple_boxes(self, test_image, human_annotator):
        """Test creating multiple new bounding boxes"""
        initial_bboxes = []
        formatted_annotations = {
            "new-uuid-1": {
                "id": "new-uuid-1",
                "category": "animal",
                "confidence": 0.9,
                "x": 0.1,
                "y": 0.2,
                "w": 0.3,
                "h": 0.4,
            },
            "new-uuid-2": {
                "id": "new-uuid-2",
                "category": "person",
                "confidence": 0.85,
                "x": 0.5,
                "y": 0.6,
                "w": 0.2,
                "h": 0.3,
            },
        }

        handle_bbox_additions(
            OBJECT_ANNOTATION_TYPE, initial_bboxes, formatted_annotations, test_image, human_annotator
        )

        assert BoundingBox.objects.filter(image=test_image).count() == 2


@pytest.mark.django_db
class TestHandleBboxDeletions:
    def test_creator_can_delete_own_bbox(self, test_image, human_annotator, user):
        """Test that creator can delete their own bbox"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )
        bbox_id = str(bbox.id)

        initial_bboxes = [bbox_id]
        formatted_annotations = {}

        handle_bbox_deletions(initial_bboxes, formatted_annotations, user, human_annotator, test_image)

        assert not BoundingBox.objects.filter(id=bbox_id).exists()

    def test_staff_can_delete_any_bbox(self, test_image, human_annotator):
        """Test that staff user can delete any bbox"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )
        bbox_id = str(bbox.id)

        # Create a staff user
        staff_user = User.objects.create_user(email="staff@test.com", is_staff=True)
        staff_annotator, _ = Annotator.objects.get_or_create(type="human", human=staff_user)

        initial_bboxes = [bbox_id]
        formatted_annotations = {}

        handle_bbox_deletions(initial_bboxes, formatted_annotations, staff_user, staff_annotator, test_image)

        assert not BoundingBox.objects.filter(id=bbox_id).exists()

    def test_non_creator_rejection_marks_invalid(self, test_image, human_annotator, user):
        """Test that non-creator rejection marks bbox as invalid"""
        bbox = BoundingBox.objects.create(
            image=test_image, x=0.1, y=0.2, w=0.3, h=0.4, created_by=human_annotator
        )
        bbox_id = str(bbox.id)

        # Create a different user
        other_user = User.objects.create_user(email="other@test.com")
        other_annotator, _ = Annotator.objects.get_or_create(type="human", human=other_user)

        initial_bboxes = [bbox_id]
        formatted_annotations = {}

        handle_bbox_deletions(initial_bboxes, formatted_annotations, other_user, other_annotator, test_image)

        bbox.refresh_from_db()
        assert bbox.validity == "INVALID"
        assert other_annotator in bbox.rejected_by.all()
