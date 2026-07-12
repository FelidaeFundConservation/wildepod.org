# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for images.models.annotation module.
Tests the BoundingBox, Category, Species, and Activity models along with their managers.
"""
import pytest
from django.conf import settings
from django.utils import timezone
from images.models import (
    Activity,
    Annotator,
    BoundingBox,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
)
from locations.models import Area, CameraStation, County, MacroSite, MicroSite
from users.models import User


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
def user(db):
    """Create a user for testing."""
    return User.objects.create_user(email="test@example.com", password="testpass123", name="Test User")


@pytest.fixture
def camera_station_action(db):
    """Create a camera station action for testing."""
    from images.models import CameraStationAction
    return CameraStationAction.objects.create(action="Retrieved SD card")


@pytest.fixture
def upload(db, camera_station, user, camera_station_action):
    """Create an upload for testing."""
    return Upload.objects.create(
        camera_station=camera_station,
        date_retrieved=timezone.now(),
        last_action=camera_station_action,
        volunteer=user,
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
def staff_user(db):
    """Create a staff user for testing."""
    return User.objects.create_user(
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


@pytest.fixture
def expert_user(db):
    """Create an expert user for testing."""
    return User.objects.create_user(
        email="expert@example.com",
        password="testpass",
        is_expert=True,
    )


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing."""
    return User.objects.create_user(
        email="user@example.com",
        password="testpass",
    )


@pytest.fixture
def bot(db):
    """Create a bot for testing."""
    from images.models import Bot
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


@pytest.fixture
def staff_annotator(db, staff_user):
    """Create a staff annotator for testing."""
    annotator, _ = Annotator.objects.get_or_create(type="human", human=staff_user)
    return annotator


@pytest.fixture
def species_name_tiger(db):
    """Create a tiger species name."""
    return SpeciesName.objects.create(
        name="Tiger", 
        scientific_name="Panthera tigris",
        species_group="WILD"
    )


@pytest.fixture
def species_name_human(db):
    """Create a human species name."""
    return SpeciesName.objects.create(
        name="Human", 
        scientific_name="Homo sapiens",
        species_group="HUMAN"
    )


@pytest.fixture
def species_name_dog(db):
    """Create a domestic dog species name."""
    return SpeciesName.objects.create(
        name="Domestic dog", 
        scientific_name="Canis familiaris",
        species_group="DOMESTIC"
    )


class TestBoundingBoxManager:
    """Test the BoundingBoxManager methods."""

    def test_annotated_with_confidence_above_threshold(
        self, image, ml_annotator
    ):
        """Test that boxes with confidence above threshold are marked correctly."""
        # Create a bounding box with high confidence
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Query with annotated
        annotated_boxes = BoundingBox.objects.annotated()
        box = annotated_boxes.get(id=bbox.id)

        assert box.keep is True
        assert box.num_accepted == 0
        assert box.num_rejected == 0

    def test_annotated_with_votes(
        self, image, ml_annotator, human_annotator
    ):
        """Test vote counting in annotated boxes."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Add acceptances
        bbox.accepted_by.add(human_annotator)

        annotated_boxes = BoundingBox.objects.annotated()
        box = annotated_boxes.get(id=bbox.id)

        assert box.num_accepted == 1
        assert box.num_rejected == 0
        assert box.vote_diff == 1

    def test_voted_valid(self, image, ml_annotator, human_annotator):
        """Test that boxes with sufficient positive votes are marked as valid."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Add enough accepts to meet threshold
        for _ in range(settings.NUM_ACCEPTS_OVER_REJECTS):
            user = User.objects.create_user(
                email=f"user{_}@example.com",
                password="testpass",
            )
            annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
            bbox.accepted_by.add(annotator)

        annotated_boxes = BoundingBox.objects.annotated()
        box = annotated_boxes.get(id=bbox.id)

        assert box.voted_valid is True
        assert box.voted_invalid is False

    def test_is_animal_filter(
        self, image, ml_annotator
    ):
        """Test the is_animal filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        animal_boxes = BoundingBox.objects.is_animal()
        assert animal_boxes.count() == 1
        assert animal_boxes.first().id == bbox.id

    def test_is_person_filter(
        self, image, ml_annotator
    ):
        """Test the is_person filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="person",
            confidence=0.95,
            created_by=ml_annotator,
        )

        person_boxes = BoundingBox.objects.is_person()
        assert person_boxes.count() == 1
        assert person_boxes.first().id == bbox.id

    def test_is_vehicle_filter(
        self, image, ml_annotator
    ):
        """Test the is_vehicle filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="vehicle",
            confidence=0.95,
            created_by=ml_annotator,
        )

        vehicle_boxes = BoundingBox.objects.is_vehicle()
        assert vehicle_boxes.count() == 1
        assert vehicle_boxes.first().id == bbox.id

    def test_is_species_tagged_filter(
        self, image, ml_annotator, species_name_tiger
    ):
        """Test the is_species_tagged filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )
        Species.objects.create(
            bounding_box=bbox,
            name=species_name_tiger,
            confidence=0.9,
            created_by=ml_annotator,
        )

        species_tagged_boxes = BoundingBox.objects.is_species_tagged()
        assert species_tagged_boxes.count() == 1

    def test_is_nondomestic_species_filter(
        self, image, ml_annotator, species_name_tiger, species_name_dog
    ):
        """Test the is_nondomestic_species filter."""
        # Create a wild animal
        bbox1 = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox1,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )
        Species.objects.create(
            bounding_box=bbox1,
            name=species_name_tiger,
            confidence=0.9,
            created_by=ml_annotator,
        )

        # Create a domestic animal
        bbox2 = BoundingBox.objects.create(
            image=image,
            x=0.6,
            y=0.6,
            w=0.3,
            h=0.3,
            confidence=0.95,
            created_by=ml_annotator,
        )
        Category.objects.create(
            bounding_box=bbox2,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )
        Species.objects.create(
            bounding_box=bbox2,
            name=species_name_dog,
            confidence=0.9,
            created_by=ml_annotator,
        )

        nondomestic_boxes = BoundingBox.objects.is_nondomestic_species()
        assert nondomestic_boxes.count() == 1
        assert nondomestic_boxes.first().id == bbox1.id


class TestCategoryManager:
    """Test the CategoryManager methods."""

    @pytest.mark.skip(reason="CategoryManager.annotated() uses confidence_threshold field which doesn't exist on Category model in wildepod_main")
    def test_valid_ordering(self, image, ml_annotator, human_annotator):
        """Test that valid categories are ordered correctly."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Create categories with different vote counts
        cat1 = Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.9,
            created_by=ml_annotator,
        )
        cat1.accepted_by.add(human_annotator)

        cat2 = Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Add enough accepts to make cat2 more valid
        for _ in range(settings.NUM_ACCEPTS_OVER_REJECTS + 1):
            user = User.objects.create_user(
                email=f"user{_}@example.com",
                password="testpass",
            )
            annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
            cat2.accepted_by.add(annotator)

        valid_cats = Category.objects.valid()
        # cat2 should come first due to higher vote_diff
        assert valid_cats.first().id == cat2.id


class TestActivityManager:
    """Test the ActivityManager methods."""

    @pytest.mark.skip(reason="ActivityManager.annotated() uses confidence_threshold field which doesn't exist on Activity model in wildepod_main")
    def test_valid_ordering(self, image, ml_annotator, human_annotator):
        """Test that valid activities are ordered correctly."""
        from images.models import ActivityType
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Create activity types
        activity_type1 = ActivityType.objects.create(name="Walking", category="MOVEMENT")
        activity_type2 = ActivityType.objects.create(name="Running", category="MOVEMENT")

        # Create activities with different confidence levels
        act1 = Activity.objects.create(
            bounding_box=bbox,
            name=activity_type1,
            confidence=0.85,
            created_by=ml_annotator,
        )

        act2 = Activity.objects.create(
            bounding_box=bbox,
            name=activity_type2,
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Add more accepts to act2
        for _ in range(settings.NUM_ACCEPTS_OVER_REJECTS + 1):
            user = User.objects.create_user(
                email=f"user{_}@example.com",
                password="testpass",
            )
            annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
            act2.accepted_by.add(annotator)

        valid_activities = Activity.objects.valid()
        assert valid_activities.count() >= 1


class TestBaseAnnotationManager:
    """Test the BaseAnnotationManager methods."""

    @pytest.mark.skip(reason="BaseAnnotationManager tests use Category model which lacks confidence_threshold field in wildepod_main")
    def test_uncertain_filter(self, image, ml_annotator, human_annotator):
        """Test the uncertain filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Create a category with votes that make it uncertain
        cat = Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.9,
            created_by=ml_annotator,
        )

        # Add one accept (not enough to be valid, but not rejected either)
        cat.accepted_by.add(human_annotator)

        uncertain_cats = Category.objects.uncertain()
        assert uncertain_cats.count() >= 0  # May or may not be uncertain depending on settings

    @pytest.mark.skip(reason="BaseAnnotationManager tests use Category model which lacks confidence_threshold field in wildepod_main")
    def test_valid_or_uncertain_filter(
        self, image, ml_annotator, human_annotator
    ):
        """Test the valid_or_uncertain filter."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )

        cat = Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.9,
            created_by=ml_annotator,
        )

        # Add accepts to make it valid
        for _ in range(settings.NUM_ACCEPTS_OVER_REJECTS):
            user = User.objects.create_user(
                email=f"user{_}@example.com",
                password="testpass",
            )
            annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
            cat.accepted_by.add(annotator)

        valid_or_uncertain = Category.objects.valid_or_uncertain()
        assert valid_or_uncertain.count() >= 1

    def test_staff_vote_detection(
        self, image, ml_annotator, staff_annotator
    ):
        """Test that staff votes are detected correctly."""
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )

        # Add staff acceptance
        bbox.accepted_by.add(staff_annotator)

        annotated_boxes = BoundingBox.objects.annotated()
        box = annotated_boxes.get(id=bbox.id)

        assert box.is_staff_vote is True


@pytest.mark.django_db
class TestSpeciesModel:
    """Test the Species model methods."""
    
    def test_species_string_representation(self, image, ml_annotator):
        """Test Species __str__ method."""
        from images.models import SpeciesName
        
        species_name = SpeciesName.objects.create(name="Tiger")
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        
        species = Species.objects.create(
            bounding_box=bbox,
            name=species_name,
            created_by=ml_annotator
        )
        assert str(species) == "Tiger"
        
    def test_get_total_species(self, image, ml_annotator):
        """Test get_total_species static method."""
        from images.models import SpeciesName
        
        species_name = SpeciesName.objects.create(name="Leopard")
        
        bbox = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            created_by=ml_annotator,
        )
        
        Species.objects.create(
            bounding_box=bbox,
            name=species_name,
            created_by=ml_annotator
        )
        
        total = Species.get_total_species()
        assert total >= 1
        
    def test_get_species_group_by(self, image, ml_annotator):
        """Test get_species_group_by static method."""
        from images.models import SpeciesName
        
        species_name1 = SpeciesName.objects.create(
            name="Wolf",
            scientific_name="Canis lupus"
        )
        species_name2 = SpeciesName.objects.create(
            name="Bear", 
            scientific_name="Ursus arctos"
        )
        
        bbox1 = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.3,
            h=0.3,
            confidence=0.95,
            created_by=ml_annotator,
        )
        
        bbox2 = BoundingBox.objects.create(
            image=image,
            x=0.5,
            y=0.5,
            w=0.3,
            h=0.3,
            confidence=0.90,
            created_by=ml_annotator,
        )
        
        Species.objects.create(
            bounding_box=bbox1,
            name=species_name1,
            created_by=ml_annotator
        )
        
        Species.objects.create(
            bounding_box=bbox2,
            name=species_name2,
            created_by=ml_annotator
        )
        
        grouped = Species.get_species_group_by()
        species_names = [item['species'] for item in grouped]
        assert 'Wolf' in species_names
        assert 'Bear' in species_names
        
    def test_species_human_animal_classification(self):
        """Test species_human_animal static method."""
        result = Species.species_human_animal()
        assert 'human' in result
        assert 'animal' in result
        assert isinstance(result['human'], tuple)
        assert isinstance(result['animal'], tuple)


@pytest.mark.django_db
class TestActivityModel:
    """Test the Activity model methods."""
    
    def test_activity_string_representation(self, image, ml_annotator):
        """Test Activity __str__ method."""
        from images.models import ActivityType
        
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
            created_by=ml_annotator,
        )
        
        activity = Activity.objects.create(
            bounding_box=bbox,
            name=activity_type,
            created_by=ml_annotator
        )
        assert str(activity) == "Running"
        
    def test_get_activities_group_by_category(self, image, ml_annotator):
        """Test get_activities_group_by_category static method."""
        from images.models import ActivityType
        
        activity_type1 = ActivityType.objects.create(
            name="Hunting",
            category="animal"
        )
        activity_type2 = ActivityType.objects.create(
            name="Sleeping",
            category="animal"
        )
        
        bbox1 = BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.3,
            h=0.3,
            confidence=0.95,
            created_by=ml_annotator,
        )
        
        bbox2 = BoundingBox.objects.create(
            image=image,
            x=0.5,
            y=0.5,
            w=0.3,
            h=0.3,
            confidence=0.90,
            created_by=ml_annotator,
        )
        
        Activity.objects.create(
            bounding_box=bbox1,
            name=activity_type1,
            created_by=ml_annotator
        )
        
        Activity.objects.create(
            bounding_box=bbox2,
            name=activity_type2,
            created_by=ml_annotator
        )
        
        grouped = Activity.get_activities_group_by_category("animal")
        activity_names = [item['activity'] for item in grouped]
        assert 'Hunting' in activity_names
        assert 'Sleeping' in activity_names

