"""
Test cases for locations models.

These are simple tests that verify basic model functionality like creation,
string representation, and relationships. They dramatically improve coverage
with minimal effort.
"""
import pytest
from locations.models import Area, County, Grid, MacroSite, MicroSite, TrailSurfaceType, TrailType


@pytest.mark.django_db
class TestAreaModel:
    """Test Area model."""

    def test_area_creation(self):
        """Test creating an Area instance."""
        area = Area.objects.create(name="North Region")
        assert area.name == "North Region"
        assert area.pk is not None

    def test_area_str_representation(self):
        """Test Area string representation."""
        area = Area.objects.create(name="South Region")
        assert str(area) == "South Region"

    def test_area_ordering(self):
        """Test Area ordering by name."""
        Area.objects.create(name="Zone C")
        Area.objects.create(name="Zone A")
        Area.objects.create(name="Zone B")
        
        areas = list(Area.objects.all())
        assert areas[0].name == "Zone A"
        assert areas[1].name == "Zone B"
        assert areas[2].name == "Zone C"


@pytest.mark.django_db
class TestCountyModel:
    """Test County model."""

    def test_county_creation(self):
        """Test creating a County with an Area."""
        area = Area.objects.create(name="Northern Area")
        county = County.objects.create(name="Alpine County", area=area)
        
        assert county.name == "Alpine County"
        assert county.area == area
        assert county.pk is not None

    def test_county_str_representation(self):
        """Test County string representation."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        assert str(county) == "Test County"

    def test_county_area_relationship(self):
        """Test County-Area relationship."""
        area = Area.objects.create(name="Region 1")
        county1 = County.objects.create(name="County 1", area=area)
        county2 = County.objects.create(name="County 2", area=area)
        
        # Check that area has multiple counties
        assert county1 in area.county_set.all()
        assert county2 in area.county_set.all()
        assert area.county_set.count() == 2


@pytest.mark.django_db
class TestMacroSiteModel:
    """Test MacroSite model."""

    def test_macrosite_creation(self):
        """Test creating a MacroSite."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Big Site", county=county)
        
        assert macro.name == "Big Site"
        assert macro.county == county
        assert macro.pk is not None

    def test_macrosite_str_representation(self):
        """Test MacroSite string representation."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Mountain Site", county=county)
        assert str(macro) == "Mountain Site"


@pytest.mark.django_db
class TestGridModel:
    """Test Grid model."""

    def test_grid_creation(self):
        """Test creating a Grid instance."""
        grid = Grid.objects.create(name="Grid A1")
        assert grid.name == "Grid A1"
        assert grid.pk is not None

    def test_grid_str_representation(self):
        """Test Grid string representation."""
        grid = Grid.objects.create(name="Grid B2")
        assert str(grid) == "Grid B2"


@pytest.mark.django_db
class TestMicroSiteModel:
    """Test MicroSite model."""

    def test_microsite_creation_with_grid(self):
        """Test creating a MicroSite with grid."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Macro Site", county=county)
        grid = Grid.objects.create(name="Grid X1")
        
        micro = MicroSite.objects.create(
            name="Small Site",
            macro_site=macro,
            grid=grid
        )
        
        assert micro.name == "Small Site"
        assert micro.macro_site == macro
        assert micro.grid == grid
        assert micro.pk is not None

    def test_microsite_creation_without_grid(self):
        """Test creating a MicroSite without grid (optional field)."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Macro Site", county=county)
        
        micro = MicroSite.objects.create(name="Tiny Site", macro_site=macro)
        
        assert micro.name == "Tiny Site"
        assert micro.macro_site == macro
        assert micro.grid is None

    def test_microsite_str_representation(self):
        """Test MicroSite string representation."""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro = MacroSite.objects.create(name="Macro Site", county=county)
        micro = MicroSite.objects.create(name="Point Site", macro_site=macro)
        assert str(micro) == "Point Site"


@pytest.mark.django_db
class TestTrailTypeModel:
    """Test TrailType model."""

    def test_trailtype_creation(self):
        """Test creating a TrailType instance."""
        trail_type = TrailType.objects.create(
            name="Hiking Trail",
            comments="Standard hiking path"
        )
        assert trail_type.name == "Hiking Trail"
        assert trail_type.comments == "Standard hiking path"
        assert trail_type.pk is not None

    def test_trailtype_creation_without_comments(self):
        """Test creating a TrailType without comments (optional field)."""
        trail_type = TrailType.objects.create(name="Mountain Path")
        assert trail_type.name == "Mountain Path"
        assert trail_type.comments == ""

    def test_trailtype_str_representation(self):
        """Test TrailType string representation."""
        trail_type = TrailType.objects.create(name="Forest Trail")
        assert str(trail_type) == "Forest Trail"


@pytest.mark.django_db
class TestTrailSurfaceTypeModel:
    """Test TrailSurfaceType model."""

    def test_trail_surface_type_creation(self):
        """Test creating a TrailSurfaceType instance."""
        surface = TrailSurfaceType.objects.create(name="Gravel")
        assert surface.name == "Gravel"
        assert surface.pk is not None

    def test_trail_surface_type_str_representation(self):
        """Test TrailSurfaceType string representation."""
        surface = TrailSurfaceType.objects.create(name="Paved")
        assert str(surface) == "Paved"
