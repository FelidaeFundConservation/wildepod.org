from django.test import Client, TestCase
from django.urls import reverse
from images.models import BoundingBox, CameraStationAction, Image, Upload
from images.views import *
from locations.models import Area, CameraStation, County, MacroSite, MicroSite
from users.models import User


# Create your tests here.
class AnnotationPagesTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(password="12345", email="jbyee2015@gmail.com")
        login = self.client.login(email="jbyee2015@gmail.com", password="12345")

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
