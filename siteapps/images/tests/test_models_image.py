"""
Tests for images.models.image module.
Tests the Image model and its manager methods.
"""
import pytest
from django.utils import timezone
from images.models import (
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
def upload_pri_1(db, camera_station, user, camera_station_action):
    """Create a priority 1 upload."""
    return Upload.objects.create(
        camera_station=camera_station,
        date_retrieved=timezone.now(),
        last_action=camera_station_action,
        volunteer=user,
        priority="1",
        dropbox_folder_name="test_folder_1",
        dropbox_folder_path="/test/path1",
        dropbox_request_id="test123",
        dropbox_request_url="https://dropbox.com/test1",
    )


@pytest.fixture
def upload_pri_2(db, camera_station, user, camera_station_action):
    """Create a priority 2 upload."""
    return Upload.objects.create(
        camera_station=camera_station,
        date_retrieved=timezone.now(),
        last_action=camera_station_action,
        volunteer=user,
        priority="2",
        dropbox_folder_name="test_folder_2",
        dropbox_folder_path="/test/path2",
        dropbox_request_id="test456",
        dropbox_request_url="https://dropbox.com/test2",
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
def human_annotator(db):
    """Create a human annotator for testing."""
    user = User.objects.create_user(
        email="annotator@example.com",
        password="testpass",
        name="Test Annotator",
    )
    annotator, _ = Annotator.objects.get_or_create(type="human", human=user)
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
    """Create a human species name with ID 8."""
    # The code expects human to have name_id=8
    species = SpeciesName.objects.create(name="Human", common_name="Human")
    # Note: In real DB, this would have id=8 but in tests we can't control auto-increment
    return species


class TestImageModel:
    """Test the Image model basic functionality."""

    def test_image_creation(self, upload_pri_1):
        """Test creating an image."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="test.jpg",
            dropbox_file_path="/test/path/test.jpg",
            dropbox_file_path_display="/test/path/test.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=1024,
        )
        assert image.dropbox_file_name == "test.jpg"
        assert image.processed is False
        assert image.deleted is False

    def test_image_str_representation(self, upload_pri_1):
        """Test the string representation of an image."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="test_image.jpg",
            dropbox_file_path="/test/path/test_image.jpg",
            dropbox_file_path_display="/test/path/test_image.jpg",
            dropbox_content_hash="abc123",
            dropbox_file_id="file_id_123",
            file_size=2048,
        )
        assert str(image) == "test_image.jpg"

    def test_image_with_coordinates(self, upload_pri_1):
        """Test creating an image with GPS coordinates."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="gps_test.jpg",
            dropbox_file_path="/test/path/gps_test.jpg",
            dropbox_file_path_display="/test/path/gps_test.jpg",
            dropbox_content_hash="def456",
            dropbox_file_id="file_id_456",
            file_size=3072,
            latitude=27.4712,
            longitude=89.6339,
        )
        assert image.latitude == 27.4712
        assert image.longitude == 89.6339

    def test_image_video_flag(self, upload_pri_1):
        """Test creating a video entry."""
        video = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="test.mp4",
            dropbox_file_path="/test/path/test.mp4",
            dropbox_file_path_display="/test/path/test.mp4",
            dropbox_content_hash="vid123",
            dropbox_file_id="file_id_vid",
            file_size=10240,
            is_video=True,
            duration=30,
        )
        assert video.is_video is True
        assert video.duration == 30

    def test_image_precomputed_flags(self, upload_pri_1):
        """Test precomputed pipeline flags."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="flags_test.jpg",
            dropbox_file_path="/test/path/flags_test.jpg",
            dropbox_file_path_display="/test/path/flags_test.jpg",
            dropbox_content_hash="flags123",
            dropbox_file_id="file_id_flags",
            file_size=2048,
            has_animals=True,
            has_wild_animals=True,
            has_bbox_above_confidence_threshold=True,
            category_pipeline_complete=True,
            use_precomputed_flags=True,
        )
        assert image.has_animals is True
        assert image.has_wild_animals is True
        assert image.has_bbox_above_confidence_threshold is True
        assert image.category_pipeline_complete is True


class TestImageManager:
    """Test the ImageManager methods."""

    def test_annotated_counts_bounding_boxes(self, upload_pri_1, ml_annotator):
        """Test that annotated method counts bounding boxes correctly."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="bbox_test.jpg",
            dropbox_file_path="/test/path/bbox_test.jpg",
            dropbox_file_path_display="/test/path/bbox_test.jpg",
            dropbox_content_hash="bbox123",
            dropbox_file_id="file_id_bbox",
            file_size=2048,
        )

        # Create bounding boxes
        BoundingBox.objects.create(
            image=image,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        BoundingBox.objects.create(
            image=image,
            x=0.6,
            y=0.6,
            w=0.3,
            h=0.3,
            confidence=0.92,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )

        annotated_images = Image.objects.annotated()
        img = annotated_images.get(id=image.id)
        assert img.num_objects == 2

    def test_annotated_counts_checkers(self, upload_pri_1, human_annotator):
        """Test that annotated method counts checkers correctly."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="checkers_test.jpg",
            dropbox_file_path="/test/path/checkers_test.jpg",
            dropbox_file_path_display="/test/path/checkers_test.jpg",
            dropbox_content_hash="check123",
            dropbox_file_id="file_id_check",
            file_size=2048,
        )

        # Add checkers
        image.bbox_checked_by.add(human_annotator)
        image.species_checked_by.add(human_annotator)
        image.activity_checked_by.add(human_annotator)

        annotated_images = Image.objects.annotated()
        img = annotated_images.get(id=image.id)
        assert img.num_bbox_checked_by == 1
        assert img.num_species_checked_by == 1
        assert img.num_activity_checked_by == 1

    def test_proportion_per_macrosite(self, macro_site, micro_site, user, camera_station_action):
        """Test proportion calculation per macrosite."""
        camera_station1 = CameraStation.objects.create(
            station_id="STATION001",
            micro_site=micro_site,
            latitude=27.5,
            longitude=90.5,
            date_deployed=timezone.now().date(),
        )
        camera_station2 = CameraStation.objects.create(
            station_id="STATION002",
            micro_site=micro_site,
            latitude=27.6,
            longitude=90.6,
            date_deployed=timezone.now().date(),
        )

        upload1 = Upload.objects.create(
            camera_station=camera_station1,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=user,
            dropbox_folder_name="test_folder_1",
            dropbox_folder_path="/path1",
            dropbox_request_id="req1",
            dropbox_request_url="https://dropbox.com/req1",
        )
        upload2 = Upload.objects.create(
            camera_station=camera_station2,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=user,
            dropbox_folder_name="test_folder_2",
            dropbox_folder_path="/path2",
            dropbox_request_id="req2",
            dropbox_request_url="https://dropbox.com/req2",
        )

        # Create images
        Image.objects.create(
            upload=upload1,
            dropbox_file_name="img1.jpg",
            dropbox_file_path="/path1/img1.jpg",
            dropbox_file_path_display="/path1/img1.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="id1",
            file_size=1024,
        )
        Image.objects.create(
            upload=upload2,
            dropbox_file_name="img2.jpg",
            dropbox_file_path="/path2/img2.jpg",
            dropbox_file_path_display="/path2/img2.jpg",
            dropbox_content_hash="hash2",
            dropbox_file_id="id2",
            file_size=1024,
        )

        proportions = Image.objects.proportion_per_macrosite()
        assert len(proportions) == 1
        assert proportions[0]["count"] == 2
        assert proportions[0]["proportion"] == 1.0

    def test_proportion_per_camera_station(self, camera_station, user, camera_station_action):
        """Test proportion calculation per camera station."""
        upload = Upload.objects.create(
            camera_station=camera_station,
            date_retrieved=timezone.now(),
            last_action=camera_station_action,
            volunteer=user,
            dropbox_folder_name="test_folder",
            dropbox_folder_path="/path",
            dropbox_request_id="req1",
            dropbox_request_url="https://dropbox.com/req1",
        )

        # Create multiple images
        for i in range(3):
            Image.objects.create(
                upload=upload,
                dropbox_file_name=f"img{i}.jpg",
                dropbox_file_path=f"/path/img{i}.jpg",
                dropbox_file_path_display=f"/path/img{i}.jpg",
                dropbox_content_hash=f"hash{i}",
                dropbox_file_id=f"id{i}",
                file_size=1024,
            )

        proportions = Image.objects.proportion_per_camera_station()
        assert len(proportions) == 1
        assert proportions[0]["count"] == 3
        assert proportions[0]["proportion"] == 1.0


class TestImageStaticMethods:
    """Test the static methods on the Image model."""

    def test_get_total_images(self, upload_pri_1):
        """Test getting total image count."""
        initial_count = Image.get_total_images()

        Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="count1.jpg",
            dropbox_file_path="/path/count1.jpg",
            dropbox_file_path_display="/path/count1.jpg",
            dropbox_content_hash="hash1",
            dropbox_file_id="id1",
            file_size=1024,
        )

        assert Image.get_total_images() == initial_count + 1

    def test_get_total_images_processed(self, upload_pri_1):
        """Test counting processed images."""
        Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="processed.jpg",
            dropbox_file_path="/path/processed.jpg",
            dropbox_file_path_display="/path/processed.jpg",
            dropbox_content_hash="hash_p",
            dropbox_file_id="id_p",
            file_size=1024,
            processed=True,
        )
        Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="not_processed.jpg",
            dropbox_file_path="/path/not_processed.jpg",
            dropbox_file_path_display="/path/not_processed.jpg",
            dropbox_content_hash="hash_np",
            dropbox_file_id="id_np",
            file_size=1024,
            processed=False,
        )

        assert Image.get_total_images_processed() >= 1
        assert Image.get_total_images_not_processed() >= 1

    def test_get_total_images_annotated_species(
        self, upload_pri_1, ml_annotator, species_name_tiger
    ):
        """Test counting images with species annotations."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="species_test.jpg",
            dropbox_file_path="/path/species_test.jpg",
            dropbox_file_path_display="/path/species_test.jpg",
            dropbox_content_hash="species_hash",
            dropbox_file_id="species_id",
            file_size=1024,
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

        Species.objects.create(
            bounding_box=bbox,
            name=species_name_tiger,
            confidence=0.9,
            created_by=ml_annotator,
        )

        species_images = Image.get_total_images_annotated_species()
        assert species_images.count() >= 1

    def test_get_total_images_annotated_category(
        self, upload_pri_1, ml_annotator
    ):
        """Test counting images with category annotations."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="category_test.jpg",
            dropbox_file_path="/path/category_test.jpg",
            dropbox_file_path_display="/path/category_test.jpg",
            dropbox_content_hash="cat_hash",
            dropbox_file_id="cat_id",
            file_size=1024,
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

        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        animal_images = Image.get_total_images_annotated_category("animal")
        assert animal_images.count() >= 1

    def test_get_total_images_annotated_exclude_category(
        self, upload_pri_1, ml_annotator
    ):
        """Test counting images excluding specific categories."""
        # Create image without category
        image1 = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="no_cat.jpg",
            dropbox_file_path="/path/no_cat.jpg",
            dropbox_file_path_display="/path/no_cat.jpg",
            dropbox_content_hash="nocat_hash",
            dropbox_file_id="nocat_id",
            file_size=1024,
        )

        # Create image with animal category
        image2 = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="with_cat.jpg",
            dropbox_file_path="/path/with_cat.jpg",
            dropbox_file_path_display="/path/with_cat.jpg",
            dropbox_content_hash="withcat_hash",
            dropbox_file_id="withcat_id",
            file_size=1024,
        )

        bbox = BoundingBox.objects.create(
            image=image2,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )

        Category.objects.create(
            bounding_box=bbox,
            name="animal",
            confidence=0.95,
            created_by=ml_annotator,
        )

        excluded_images = Image.get_total_images_annotated_exclude_category("animal")
        # image1 should be in excluded (has no categories)
        assert image1 in excluded_images

    def test_get_total_images_priorities(self, upload_pri_1, upload_pri_2):
        """Test counting images by priority."""
        # Create images for different priorities
        Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="pri1.jpg",
            dropbox_file_path="/path/pri1.jpg",
            dropbox_file_path_display="/path/pri1.jpg",
            dropbox_content_hash="pri1_hash",
            dropbox_file_id="pri1_id",
            file_size=1024,
        )
        Image.objects.create(
            upload=upload_pri_2,
            dropbox_file_name="pri2.jpg",
            dropbox_file_path="/path/pri2.jpg",
            dropbox_file_path_display="/path/pri2.jpg",
            dropbox_content_hash="pri2_hash",
            dropbox_file_id="pri2_id",
            file_size=1024,
        )

        priorities = Image.get_total_images_priorities()
        assert "priority_1" in priorities
        assert "priority_2" in priorities
        assert priorities["priority_1"] >= 1
        assert priorities["priority_2"] >= 1

    def test_get_untouched_images(self, upload_pri_1, ml_annotator, human_annotator):
        """Test counting untouched images (no accepts/rejects)."""
        # Create an untouched image
        image1 = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="untouched.jpg",
            dropbox_file_path="/path/untouched.jpg",
            dropbox_file_path_display="/path/untouched.jpg",
            dropbox_content_hash="untouched_hash",
            dropbox_file_id="untouched_id",
            file_size=1024,
        )
        bbox1 = BoundingBox.objects.create(
            image=image1,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )

        # Create a touched image
        image2 = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="touched.jpg",
            dropbox_file_path="/path/touched.jpg",
            dropbox_file_path_display="/path/touched.jpg",
            dropbox_content_hash="touched_hash",
            dropbox_file_id="touched_id",
            file_size=1024,
        )
        bbox2 = BoundingBox.objects.create(
            image=image2,
            x=0.1,
            y=0.1,
            w=0.5,
            h=0.5,
            confidence=0.95,
            confidence_threshold=0.8,
            created_by=ml_annotator,
        )
        bbox2.accepted_by.add(human_annotator)

        untouched_count = Image.get_untouched_images()
        assert untouched_count >= 1


@pytest.mark.django_db
class TestImageEdgeCases:
    """Test edge cases and less commonly used Image model methods."""
    
    def test_image_with_null_coordinates(self, upload_pri_1):
        """Test image with null latitude/longitude."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="no_coords.jpg",
            dropbox_file_path="/path/no_coords.jpg",
            dropbox_file_path_display="/path/no_coords.jpg",
            dropbox_content_hash="no_coords_hash",
            dropbox_file_id="no_coords_id",
            file_size=1024,
            latitude=None,
            longitude=None
        )
        assert image.latitude is None
        assert image.longitude is None
        
    def test_get_species_annotated_method(self):
        """Test get_species_annotated static method with species IDs."""
        # This tests line 236 - the raw SQL method
        from images.models import Image
        species_ids = [1, 2, 3]
        # This method calls a raw SQL function
        result = Image.get_species_annotated(species_ids)
        # Result type depends on implementation
        assert result is not None
        
    def test_image_with_extreme_coordinates(self, upload_pri_1):
        """Test image with edge case coordinates."""
        image = Image.objects.create(
            upload=upload_pri_1,
            dropbox_file_name="extreme_coords.jpg",
            dropbox_file_path="/path/extreme_coords.jpg",
            dropbox_file_path_display="/path/extreme_coords.jpg",
            dropbox_content_hash="extreme_coords_hash",
            dropbox_file_id="extreme_coords_id",
            file_size=1024,
            latitude=90.0,  # North pole
            longitude=180.0  # Date line
        )
        assert image.latitude == 90.0
        assert image.longitude == 180.0
