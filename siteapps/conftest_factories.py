"""Factory Boy factories for generating test data"""
import factory
from datetime import datetime, date
from django.contrib.auth import get_user_model
from django.utils import timezone
from locations.models import (
    Area, County, MacroSite, Grid, MicroSite, 
    TrailType, TrailSurfaceType, CameraStation
)
from images.models import (
    Upload, Image, CameraStationAction, Bot, Annotator,
    BoundingBox, Category, Species, SpeciesName, Activity, ActivityType
)
from explore.models import Snapshot

User = get_user_model()


# ============ Users ============
class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ('email',)
    
    email = factory.Sequence(lambda n: f'user{n}@test.com')
    name = factory.Faker('name')
    is_active = True
    is_staff = False
    is_superuser = False


class StaffUserFactory(UserFactory):
    is_staff = True


class SuperUserFactory(UserFactory):
    is_staff = True
    is_superuser = True


# ============ Locations ============
class AreaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Area
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Area {n}')


class CountyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = County
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'County {n}')
    area = factory.SubFactory(AreaFactory)


class MacroSiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MacroSite
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Macro Site {n}')
    county = factory.SubFactory(CountyFactory)


class GridFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Grid
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Grid {n}')


class MicroSiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MicroSite
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Micro Site {n}')
    macro_site = factory.SubFactory(MacroSiteFactory)
    grid = factory.SubFactory(GridFactory)


class TrailTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrailType
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Trail Type {n}')


class TrailSurfaceTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrailSurfaceType
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Surface Type {n}')


class CameraStationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CameraStation
        django_get_or_create = ('station_id',)
    
    station_id = factory.Sequence(lambda n: f'CAM{n:04d}')
    micro_site = factory.SubFactory(MicroSiteFactory)
    latitude = factory.Faker('latitude')
    longitude = factory.Faker('longitude')
    date_deployed = factory.LazyFunction(date.today)


# ============ Images & Uploads ============
class CameraStationActionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CameraStationAction
        django_get_or_create = ('action',)
    
    action = factory.Sequence(lambda n: f'Action {n}')


class UploadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Upload
    
    camera_station = factory.SubFactory(CameraStationFactory)
    date_retrieved = factory.LazyFunction(lambda: timezone.now())
    last_action = factory.SubFactory(CameraStationActionFactory)
    volunteer = factory.SubFactory(UserFactory)
    dropbox_folder_name = factory.Sequence(lambda n: f"test_upload_{n}")
    dropbox_folder_path = factory.Sequence(lambda n: f"/test/uploads/test_upload_{n}")
    dropbox_request_id = factory.Sequence(lambda n: f"req_{n}")
    dropbox_request_url = factory.Sequence(lambda n: f"https://dropbox.com/request/{n}")


class ImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Image
    
    upload = factory.SubFactory(UploadFactory)
    dropbox_file_path = factory.Sequence(lambda n: f'/test/images/IMG_{n:04d}.jpg')
    dropbox_file_name = factory.Sequence(lambda n: f'IMG_{n:04d}.jpg')
    dropbox_file_path_display = factory.Sequence(lambda n: f'/test/images/IMG_{n:04d}.jpg')
    dropbox_content_hash = factory.Faker('sha256')
    dropbox_file_id = factory.Sequence(lambda n: f'id:{n}')
    file_size = factory.Faker('random_int', min=100000, max=5000000)
    trigger_timestamp = factory.LazyFunction(lambda: timezone.now())


# ============ Annotations ============
class BotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bot
        django_get_or_create = ('name', 'version')
    
    name = 'MegaDetector'
    version = 'v5a.0.0'
    task_type = 'Object Detection'
    threshold = 0.2


class AnnotatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Annotator
    
    type = 'human'
    human = factory.SubFactory(UserFactory)
    
    class Params:
        bot_annotator = factory.Trait(
            type='bot',
            human=None,
            bot=factory.SubFactory(BotFactory)
        )


class BoundingBoxFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BoundingBox
    
    image = factory.SubFactory(ImageFactory)
    x = factory.Faker('pyfloat', min_value=0, max_value=0.8)
    y = factory.Faker('pyfloat', min_value=0, max_value=0.8)
    w = factory.Faker('pyfloat', min_value=0.1, max_value=0.2)
    h = factory.Faker('pyfloat', min_value=0.1, max_value=0.2)
    confidence = factory.Faker('pyfloat', min_value=0.5, max_value=1.0)
    created_by = factory.SubFactory(AnnotatorFactory)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category
    
    bounding_box = factory.SubFactory(BoundingBoxFactory)
    name = factory.Iterator(['animal', 'person', 'vehicle'])
    confidence = factory.Faker('pyfloat', min_value=0.5, max_value=1.0)
    created_by = factory.SubFactory(AnnotatorFactory)


class SpeciesNameFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SpeciesName
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Species {n}')
    species_group = 'animal'


class SpeciesFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Species
    
    bounding_box = factory.SubFactory(BoundingBoxFactory)
    name = factory.SubFactory(SpeciesNameFactory)
    confidence = factory.Faker('pyfloat', min_value=0.5, max_value=1.0)
    created_by = factory.SubFactory(AnnotatorFactory)


class ActivityTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ActivityType
        django_get_or_create = ('name',)
    
    name = factory.Sequence(lambda n: f'Activity {n}')
    category = 'Moving'


class ActivityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Activity
    
    bounding_box = factory.SubFactory(BoundingBoxFactory)
    name = factory.SubFactory(ActivityTypeFactory)
    confidence = factory.Faker('pyfloat', min_value=0.5, max_value=1.0)
    created_by = factory.SubFactory(AnnotatorFactory)


# ============ Explore ============
class SnapshotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Snapshot
    
    volunteer = factory.SubFactory(UserFactory)
    status = 'pending'
    
    @factory.post_generation
    def macrosites(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for macrosite in extracted:
                self.macrosites.add(macrosite)
