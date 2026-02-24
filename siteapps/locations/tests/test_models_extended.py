"""Extended tests for locations models to increase coverage"""
import pytest
from locations.models import (
    Area,
    CameraStation,
    County,
    Grid,
    MacroSite,
    MicroSite,
    TrailSurfaceType,
    TrailType,
)


@pytest.mark.django_db
class TestAreaModelExtended:
    def test_area_creation_basic(self):
        """Test creating area"""
        area = Area.objects.create(name="Test Area")

        assert area.name == "Test Area"
        assert str(area) == "Test Area"

    def test_area_unique_name_constraint(self):
        """Test that area names must be unique"""
        Area.objects.create(name="Unique Area")

        # Creating another area with same name should fail
        with pytest.raises(Exception):  # IntegrityError
            Area.objects.create(name="Unique Area")


@pytest.mark.django_db
class TestCountyModelExtended:
    def test_county_with_multiple_macrosites(self):
        """Test county with multiple macrosites"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)

        macro1 = MacroSite.objects.create(name="Macro 1", county=county)
        macro2 = MacroSite.objects.create(name="Macro 2", county=county)

        assert county.macrosite_set.count() == 2
        assert macro1 in county.macrosite_set.all()
        assert macro2 in county.macrosite_set.all()

    def test_county_protect_on_area_delete(self):
        """Test that deleting area with county raises ProtectedError"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)

        # Attempting to delete area should fail due to PROTECT
        with pytest.raises(Exception):  # ProtectedError
            area.delete()


@pytest.mark.django_db
class TestMacroSiteModelExtended:
    def test_macrosite_basic_creation(self):
        """Test macrosite basic creation"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Macro Site", county=county)

        assert macro.name == "Macro Site"
        assert macro.county == county

    def test_macrosite_protect_on_county_delete(self):
        """Test that deleting county with macrosite raises ProtectedError"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)

        # Attempting to delete county should fail due to PROTECT
        with pytest.raises(Exception):  # ProtectedError
            county.delete()


@pytest.mark.django_db
class TestGridModelExtended:
    def test_grid_unique_name(self):
        """Test grid name"""
        grid1 = Grid.objects.create(name="Grid 1")
        grid2 = Grid.objects.create(name="Grid 2")

        assert grid1.name == "Grid 1"
        assert grid2.name == "Grid 2"
        assert Grid.objects.count() == 2


@pytest.mark.django_db
class TestMicroSiteModelExtended:
    def test_microsite_with_grid(self):
        """Test microsite with grid relationship"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        grid = Grid.objects.create(name="Test Grid")

        micro = MicroSite.objects.create(
            name="Micro with grid",
            macro_site=macro,
            grid=grid,
        )

        assert micro.grid == grid
        assert micro in grid.microsite_set.all()

    def test_microsite_null_grid(self):
        """Test microsite without grid"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)

        micro = MicroSite.objects.create(
            name="Micro without grid",
            macro_site=macro,
        )

        assert micro.grid is None

    def test_microsite_protect_on_macrosite_delete(self):
        """Test that deleting macrosite with microsite raises ProtectedError"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(
            name="Test Micro",
            macro_site=macro,
        )

        # Attempting to delete macro should fail due to PROTECT
        with pytest.raises(Exception):  # ProtectedError
            macro.delete()


@pytest.mark.django_db
class TestCameraStationModelExtended:
    def test_camera_station_with_all_fields(self):
        """Test camera station with all fields populated"""
        from datetime import date

        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)

        station = CameraStation.objects.create(
            station_id="CAM001",
            micro_site=micro,
            latitude=40.7128,
            longitude=-74.0060,
            elevation=100,
            date_deployed=date(2024, 1, 1),
        )

        assert station.station_id == "CAM001"
        assert station.elevation == 100
        assert station.latitude == 40.7128
        assert station.longitude == -74.0060

    def test_camera_station_minimal_fields(self):
        """Test camera station with minimal required fields"""
        from datetime import date

        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)

        station = CameraStation.objects.create(
            station_id="CAM002",
            micro_site=micro,
            latitude=40.7128,
            longitude=-74.0060,
            date_deployed=date(2024, 1, 1),
        )

        assert station.station_id == "CAM002"
        assert station.elevation is None

    def test_camera_station_protect_on_microsite_delete(self):
        """Test that deleting microsite with camera station raises ProtectedError"""
        from datetime import date

        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM003",
            micro_site=micro,
            latitude=40.7128,
            longitude=-74.0060,
            date_deployed=date(2024, 1, 1),
        )

        # Attempting to delete micro should fail due to PROTECT
        with pytest.raises(Exception):  # ProtectedError
            micro.delete()


@pytest.mark.django_db
class TestTrailTypeModelExtended:
    def test_trail_type_with_long_comments(self):
        """Test trail type with long comments"""
        long_comment = "This is a very long comment " * 10
        trail_type = TrailType.objects.create(
            name="Trail Type 1",
            comments=long_comment,
        )

        assert len(trail_type.comments) > 100
        assert trail_type.comments == long_comment

    def test_trail_type_blank_comments(self):
        """Test trail type with blank comments"""
        trail_type = TrailType.objects.create(name="Trail Type 2")

        assert trail_type.comments == ""


@pytest.mark.django_db
class TestTrailSurfaceTypeModelExtended:
    def test_trail_surface_type_multiple(self):
        """Test creating multiple trail surface types"""
        surf1 = TrailSurfaceType.objects.create(name="Paved")
        surf2 = TrailSurfaceType.objects.create(name="Gravel")
        surf3 = TrailSurfaceType.objects.create(name="Dirt")

        assert TrailSurfaceType.objects.count() == 3
        assert surf1.name == "Paved"
        assert surf2.name == "Gravel"
        assert surf3.name == "Dirt"


@pytest.mark.django_db
class TestLocationHierarchy:
    def test_full_location_hierarchy(self):
        """Test the full hierarchy from area to camera station"""
        from datetime import date

        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM001",
            micro_site=micro,
            latitude=40.7128,
            longitude=-74.0060,
            date_deployed=date(2024, 1, 1),
        )

        # Verify relationships work both ways
        assert county.area == area
        assert macro.county == county
        assert micro.macro_site == macro
        assert station.micro_site == micro

        # Verify reverse relationships
        assert county in area.county_set.all()
        assert macro in county.macrosite_set.all()
        assert micro in macro.microsite_set.all()
        assert station in micro.camerastation_set.all()

    def test_protect_prevents_cascade_delete(self):
        """Test that PROTECT prevents deletion through hierarchy"""
        from datetime import date

        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Test Macro", county=county)
        micro = MicroSite.objects.create(name="Test Micro", macro_site=macro)
        station = CameraStation.objects.create(
            station_id="CAM001",
            micro_site=micro,
            latitude=40.7128,
            longitude=-74.0060,
            date_deployed=date(2024, 1, 1),
        )

        # Trying to delete any level should fail due to PROTECT
        with pytest.raises(Exception):  # ProtectedError
            area.delete()
