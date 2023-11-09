from datetime import datetime

from django.test import Client, TestCase
from django.urls import reverse
from images.models import Annotator, BoundingBox, CameraStationAction, Image, Upload
from images.views import *
from locations.models import Area, CameraStation, County, MacroSite, MicroSite
from users.models import User


def createTestUserObject(name):
    email = f"{name}@fakewildepodaccount.com"
    password = name
    user = User.objects.create_user(password=password, email=email)

    return user, email, password


def createTestUploadObject(self):
    return Upload.objects.create(
        camera_station=CameraStation.objects.get_or_create(
            station_id="test_station",
            latitude=0,
            longitude=0,
            micro_site=MicroSite.objects.get_or_create(
                name="test_microsite",
                macro_site=MacroSite.objects.get_or_create(
                    name="test_macrosite",
                    county=County.objects.get_or_create(
                        name="test_county", area=Area.objects.get_or_create(name="test_area")[0]
                    )[0],
                )[0],
            )[0],
            date_deployed=datetime.now(),
        )[0],
        date_retrieved=datetime.now(),
        last_action=CameraStationAction.objects.get_or_create(action="test_camera_station_action")[0],
        volunteer=self.user,
        dropbox_folder_name="test_dropbox_folder_name",
        dropbox_folder_path="test_dropbox_folder_path",
        dropbox_request_id="test_dropbox_request_id",
        dropbox_request_url="test_dropbox_request_url",
        priority="4",
    )


def createTestImageObject(test_upload_object):
    return Image.objects.create(
        upload=test_upload_object,
        dropbox_file_name="test_dropbox_file_name",
        dropbox_file_path="test_dropbox_file_path",
        dropbox_file_path_display="test_dropbox_file_path_display",
        dropbox_content_hash="test_dropbox_content_hash",
        dropbox_file_id="test_dropbox_file_id",
        file_size=0,
    )


def createTestBoundingBoxObject(test_image_object, test_user_object):
    return BoundingBox.objects.create(image=test_image_object, x=0, y=0, w=0, h=0, created_by=test_user_object)


# Create your tests here.
class AnnotationPagesTestCase(TestCase):
    def setUp(self):
        self.user, email, password = createTestUserObject("Justin")
        self.client.login(email=email, password=password)

    def test_object_page_loads(self):
        response = self.client.get(reverse("images:annotate_objects"))
        self.assertEqual(response.status_code, 200)

    def test_species_page_loads(self):
        response = self.client.get(reverse("images:annotate_species"))
        self.assertEqual(response.status_code, 200)

    def test_animal_activity_page_loads(self):
        response = self.client.get(reverse("images:annotate_activity", kwargs={"category": "animal"}))
        self.assertEqual(response.status_code, 200)

    def test_human_activity_page_loads(self):
        response = self.client.get(reverse("images:annotate_activity", kwargs={"category": "human"}))
        self.assertEqual(response.status_code, 200)

    def test_custom_annotations_page_loads(self):
        response = self.client.get(reverse("images:custom_annotation"))
        self.assertEqual(response.status_code, 200)


class AnnotationProcessorTestCase(TestCase):
    def setUp(self):
        self.user, email, password = createTestUserObject("Justin")
        self.client.login(email=email, password=password)
        self.annotator, created = Annotator.objects.get_or_create(type="human", human=self.user)
        test_upload_object = createTestUploadObject(self)

        test_image_object = createTestImageObject(test_upload_object)
        self.test_image = test_image_object

    def test_category_submission(self):
        boxNum = 5
        boxList = []

        while boxNum > 0:
            boxList.append(createTestBoundingBoxObject(self.test_image, self.annotator))
            boxNum -= 1

        self.assertEqual(len(boxList), 5)
