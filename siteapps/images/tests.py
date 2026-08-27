# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from datetime import datetime

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from images.management.commands.ingest_annotations import (
    _extract_scientific_name_from_prediction,
    ingest_megadetector,
    ingest_speciesnet,
)
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    Bot,
    BoundingBox,
    CameraStationAction,
    Category,
    Image,
    Species,
    SpeciesName,
    Upload,
)
from images.processors import process_activity_annotations, process_species_annotations, vote
from images.views.annotation import (
    annotate,
    calculateActivityAnnotationFlags,
    calculateCategoryAnnotationFlags,
    calculateSpeciesAnnotationFlags,
    skip_ineligible_images,
)
from locations.models import Area, CameraStation, County, MacroSite, MicroSite
from users.models import User


def create_test_user_object(name):
    email = f"{name}@fakewildepodaccount.com"
    password = name
    user = User.objects.create_user(password=password, email=email)

    return user, email, password


def create_test_upload_object(self):
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


def create_test_image_object(test_upload_object, content_hash: str):
    return Image.objects.create(
        upload=test_upload_object,
        dropbox_file_name="test_dropbox_file_name",
        dropbox_file_path="test_dropbox_file_path",
        dropbox_file_path_display="test_dropbox_file_path_display",
        dropbox_content_hash=content_hash if content_hash else "test_dropbox_content_hash",
        dropbox_file_id="test_dropbox_file_id",
        file_size=0,
    )


def create_test_bounding_box_object(test_image_object, test_user_object):
    return BoundingBox.objects.create(image=test_image_object, x=0, y=0, w=0, h=0, created_by=test_user_object)


def create_test_bboxes(test_image_object, test_user_object, num_boxes):
    box_list = []

    while num_boxes > 0:
        box_list.append(create_test_bounding_box_object(test_image_object, test_user_object))
        num_boxes -= 1

    return box_list if len(box_list) > 1 else box_list[0]


def create_test_category_object(test_bounding_box_object, name, test_annotator_object):
    return Category.objects.create(
        bounding_box=test_bounding_box_object,
        name=name,
        created_by=test_annotator_object,
        confidence=1,
    )


def create_test_species_object(test_bounding_box_object, name, group, test_annotator_object):
    return Species.objects.create(
        bounding_box=test_bounding_box_object,
        name=SpeciesName.objects.get_or_create(name=name, species_group=group)[0],
        created_by=test_annotator_object,
        confidence=1,
    )


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user, email, password = create_test_user_object("Justin")
        self.client.login(email=email, password=password)

        self.annotator, created = Annotator.objects.get_or_create(type="human", human=self.user)

        test_upload_object = create_test_upload_object(self)

        test_image_object = create_test_image_object(test_upload_object)
        test_image_object.processed = True
        test_image_object.save()

        self.test_image = test_image_object
        self.test_upload = test_upload_object


# Create your tests here.
class AnnotationPagesTestCase(LoggedInTestCase):
    def setUp(self):
        super().setUp()

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


class AnnotationFlagsTestCase(LoggedInTestCase):
    def setUp(self):
        # Create test user and login with it
        super().setUp()

        self.other_user, email, password = create_test_user_object("OtherUser")
        self.other_annotator, created = Annotator.objects.get_or_create(type="human", human=self.other_user)

        bot, created = Bot.objects.get_or_create(name="MegaDetector", version="0.0")
        self.megadetector_annotator, created = Annotator.objects.get_or_create(type="bot", bot=bot)


class SingleBoxSingleCategoryTestCase(AnnotationFlagsTestCase):
    """
    When a regular user is the first to vote and creates a new category object
    """

    def test_category_creation_regular_user(self):
        # Check we're using a nonstaff and nonexpert user
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        category1 = create_test_category_object(bbox1, "person", self.annotator)

        debug_info = calculateCategoryAnnotationFlags(self.test_image)

        self.assertFalse(not debug_info["flag_checks"]["or_checks"]["category_has_uncertain"])
        self.assertFalse(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(debug_info["flag_checks"]["bounding_boxes_gte_zero"])

        self.assertFalse(self.test_image.category_pipeline_complete)
        self.assertFalse(self.test_image.has_humans)
        self.assertFalse(self.test_image.has_animals)
        self.assertFalse(self.test_image.has_vehicles)

    """
    When a staff user is the first to vote and creates a new category object
    """

    def test_category_creation_staff_user(self):
        # Make user staff
        self.user.is_staff = True
        self.user.save()

        # Check we're using a staff and nonexpert user
        self.assertTrue(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        category1 = create_test_category_object(bbox1, "animal", self.annotator)

        debug_info = calculateCategoryAnnotationFlags(self.test_image)

        self.assertTrue(not debug_info["flag_checks"]["or_checks"]["category_has_uncertain"])
        self.assertTrue(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(debug_info["flag_checks"]["bounding_boxes_gte_zero"])

        self.assertTrue(self.test_image.category_pipeline_complete)
        self.assertFalse(self.test_image.has_humans)
        self.assertTrue(self.test_image.has_animals)
        self.assertFalse(self.test_image.has_vehicles)

    """
    When an expert user is the first to vote and creates a new category object
    """

    def test_category_creation_expert_user(self):
        # Make user expert
        self.user.is_expert = True
        self.user.save()

        # Check we're using a nonstaff and expert user
        self.assertFalse(self.user.is_staff)
        self.assertTrue(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        category1 = create_test_category_object(bbox1, "vehicle", self.annotator)

        debug_info = calculateCategoryAnnotationFlags(self.test_image)

        self.assertTrue(not debug_info["flag_checks"]["or_checks"]["category_has_uncertain"])
        self.assertTrue(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(debug_info["flag_checks"]["bounding_boxes_gte_zero"])

        self.assertTrue(self.test_image.category_pipeline_complete)
        self.assertFalse(self.test_image.has_humans)
        self.assertFalse(self.test_image.has_animals)
        self.assertTrue(self.test_image.has_vehicles)

    """
    When a regular user accepts a created category by another regular annotator
    """

    def test_category_acception_regular_user(self):
        # Check we're using a nonstaff and nonexpert user
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Check the other user is the same
        self.assertFalse(self.other_user.is_staff)
        self.assertFalse(self.other_user.is_expert)

        # Setup objects
        bbox1 = create_test_bboxes(
            test_image_object=self.test_image, test_user_object=self.other_annotator, num_boxes=1
        )
        category1 = create_test_category_object(bbox1, "vehicle", self.other_annotator)

        # Check that the category was created successfully
        self.assertEquals(category1.created_by, self.other_annotator)

        # Make the vote
        vote(category1, self.annotator, accept=True)
        vote(bbox1, self.annotator, accept=True)

        # Check flags
        debug_info = calculateCategoryAnnotationFlags(self.test_image)

        self.assertTrue(not debug_info["flag_checks"]["or_checks"]["category_has_uncertain"])
        self.assertFalse(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(debug_info["flag_checks"]["bounding_boxes_gte_zero"])

        self.assertTrue(self.test_image.category_pipeline_complete)
        self.assertFalse(self.test_image.has_humans)
        self.assertFalse(self.test_image.has_animals)
        self.assertTrue(self.test_image.has_vehicles)

    """
    When a regular user accepts a MegaDetector annotation
    """

    def test_megadetector_category_acception_regular_user(self):
        # Check we're using a nonstaff and nonexpert user
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Check that the category creator is a bot
        self.assertEquals(self.megadetector_annotator.type, "bot")

        # Setup objects
        bbox1 = create_test_bboxes(
            test_image_object=self.test_image, test_user_object=self.megadetector_annotator, num_boxes=1
        )
        category1 = create_test_category_object(bbox1, "person", self.megadetector_annotator)

        # Make the vote
        vote(category1, self.annotator, accept=True)
        vote(bbox1, self.annotator, accept=True)

        # Check flags
        debug_info = calculateCategoryAnnotationFlags(self.test_image)

        self.assertFalse(not debug_info["flag_checks"]["or_checks"]["category_has_uncertain"])
        self.assertFalse(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(debug_info["flag_checks"]["bounding_boxes_gte_zero"])

        self.assertFalse(self.test_image.category_pipeline_complete)
        self.assertFalse(self.test_image.has_humans)
        self.assertFalse(self.test_image.has_animals)
        self.assertFalse(self.test_image.has_vehicles)


class SingleBoxSingleSpeciesTestCase(AnnotationFlagsTestCase):
    """
    When a regular user is the first to vote and creates a new species object
    """

    def setUp(self):
        super().setUp()

        # Set the prerequisite flags
        self.test_image.processed = True
        self.test_image.has_animals = True
        self.test_image.save()

    def test_species_creation_regular_user(self):
        # Check prerequisite flags
        self.assertTrue(self.test_image.processed)
        self.assertTrue(self.test_image.has_animals)

        # Check we're using a nonstaff and nonexpert user
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        species1 = create_test_species_object(bbox1, "Mule Deer", "WILD", self.annotator)

        # Category complete is a prerequisite to species complete, set this to true
        self.test_image.category_pipeline_complete = True
        debug_info = calculateSpeciesAnnotationFlags(self.test_image)
        self.test_image.save()

        self.assertFalse(not debug_info["flag_checks"]["species_has_uncertain"])
        self.assertFalse(debug_info["flag_checks"]["species_has_valid"])

        self.assertFalse(debug_info["flag_checks"]["or_checks"]["checked_by"])
        self.assertFalse(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertFalse(self.test_image.species_pipeline_complete)
        self.assertFalse(self.test_image.has_wild_animals)

    """
    When a staff user is the first to vote and creates a new species object
    """

    def test_species_creation_staff_user(self):
        # Check prerequisite flags
        self.assertTrue(self.test_image.processed)
        self.assertTrue(self.test_image.has_animals)

        # Make user staff
        self.user.is_staff = True
        self.user.save()

        # Check we're using a staff and nonexpert user
        self.assertTrue(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        species1 = create_test_species_object(bbox1, "Domestic horse", "DOMESTIC", self.annotator)

        # Category complete is a prerequisite to species complete, set this to true
        self.test_image.category_pipeline_complete = True
        debug_info = calculateSpeciesAnnotationFlags(self.test_image)
        self.test_image.save()

        self.assertTrue(not debug_info["flag_checks"]["species_has_uncertain"])
        self.assertTrue(debug_info["flag_checks"]["species_has_valid"])

        self.assertFalse(debug_info["flag_checks"]["or_checks"]["checked_by"])
        self.assertTrue(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(self.test_image.species_pipeline_complete)
        self.assertFalse(self.test_image.has_wild_animals)

    """
    When an expert user is the first to vote and creates a new species object
    """

    def test_species_creation_expert_user(self):
        # Check prerequisite flags
        self.assertTrue(self.test_image.processed)
        self.assertTrue(self.test_image.has_animals)

        # Make user expert
        self.user.is_expert = True
        self.user.save()

        # Check we're using a nonstaff and expert user
        self.assertFalse(self.user.is_staff)
        self.assertTrue(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        species1 = create_test_species_object(bbox1, "Raccoon", "WILD", self.annotator)

        # Category complete is a prerequisite to species complete, set this to true
        self.test_image.category_pipeline_complete = True
        debug_info = calculateSpeciesAnnotationFlags(self.test_image)
        self.test_image.save()

        self.assertTrue(not debug_info["flag_checks"]["species_has_uncertain"])
        self.assertTrue(debug_info["flag_checks"]["species_has_valid"])

        self.assertFalse(debug_info["flag_checks"]["or_checks"]["checked_by"])
        self.assertTrue(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(self.test_image.species_pipeline_complete)
        self.assertTrue(self.test_image.has_wild_animals)

    """
    When a regular user accepts a created species by another regular annotator
    """

    def test_species_acception_regular_user(self):
        # Check prerequisite flags
        self.assertTrue(self.test_image.processed)
        self.assertTrue(self.test_image.has_animals)

        # Check we're using a nonstaff and nonexpert user
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_expert)

        # Check the other user is the same
        self.assertFalse(self.other_user.is_staff)
        self.assertFalse(self.other_user.is_expert)

        # Setup objects
        bbox1 = create_test_bboxes(
            test_image_object=self.test_image, test_user_object=self.other_annotator, num_boxes=1
        )
        species1 = create_test_species_object(bbox1, "Unknown", "OTHER", self.other_annotator)
        self.test_image.species_checked_by.add(self.other_annotator)

        # Check that the species was created successfully
        self.assertEquals(species1.created_by, self.other_annotator)

        # Make the vote
        vote(species1, self.annotator, accept=True)
        vote(bbox1, self.annotator, accept=True)
        self.test_image.species_checked_by.add(self.annotator)

        # Category complete is a prerequisite to species complete, set this to true
        self.test_image.category_pipeline_complete = True
        debug_info = calculateSpeciesAnnotationFlags(self.test_image)
        self.test_image.save()

        self.assertTrue(not debug_info["flag_checks"]["species_has_uncertain"])
        self.assertTrue(debug_info["flag_checks"]["species_has_valid"])

        self.assertTrue(debug_info["flag_checks"]["or_checks"]["checked_by"])
        self.assertFalse(debug_info["flag_checks"]["or_checks"]["has_staff_or_expert_vote"])

        self.assertTrue(self.test_image.species_pipeline_complete)
        self.assertFalse(self.test_image.has_wild_animals)


class ObjectValidityTestCase(LoggedInTestCase):
    def setUp(self):
        super().setUp()

        self.other_user1, email, password = create_test_user_object("OtherUser1")
        self.other_annotator1, created = Annotator.objects.get_or_create(type="human", human=self.other_user1)

        self.other_user2, email, password = create_test_user_object("OtherUser2")
        self.other_annotator2, created = Annotator.objects.get_or_create(type="human", human=self.other_user2)

        self.other_user3, email, password = create_test_user_object("OtherUser3")
        self.other_annotator3, created = Annotator.objects.get_or_create(type="human", human=self.other_user3)

        # Setup objects
        self.bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)

    """
    Staff/expert rejections should outweigh all regular users' acceptions
    """

    def test_expert_rejection_overrules_regular_acceptions(self):
        # Make user expert
        self.user.is_expert = True
        self.user.save()

        # Check we're using an expert
        self.assertTrue(self.user.is_expert)

        # Check the other voters are non-expert and non-staff
        self.assertFalse(self.other_user1.is_expert)
        self.assertFalse(self.other_user1.is_staff)
        self.assertFalse(self.other_user2.is_expert)
        self.assertFalse(self.other_user2.is_staff)
        self.assertFalse(self.other_user3.is_expert)
        self.assertFalse(self.other_user3.is_staff)

        # Make the accepting votes by other annotators
        species1 = create_test_species_object(self.bbox1, "Mule Deer", "WILD", self.other_annotator1)
        vote(species1, self.other_annotator2, accept=True)
        vote(species1, self.other_annotator3, accept=True)

        # Make the rejecting vote by the expert user
        vote(species1, self.annotator, accept=False)

        # Check the votes were applied as expected
        self.assertEqual(species1.accepted_by.count(), 2)
        self.assertEqual(species1.rejected_by.count(), 1)

        # Get the object validity
        species_obj = Species.objects.filter(id=species1.id)
        species_values = species_obj.values()

        zipped_species_querysets = list(zip(species_obj, species_values))
        annotate(zipped_species_querysets)

        self.assertEqual(zipped_species_querysets[0][1].get("status"), "INVALID")

    """
    One-to-one staff acception to rejection ratio shouldn't affect it
    """

    def test_expert_rejection_versus_acception(self):
        # Make users expert
        self.user.is_expert = True
        self.user.save()

        self.other_user1.is_expert = True
        self.other_user1.save()

        # Check we're using experts
        self.assertTrue(self.user.is_expert)
        self.assertTrue(self.other_user1.is_expert)

        # Make the rejecting votes by other annotator
        species1 = create_test_species_object(self.bbox1, "Bobcat", "WILD", self.other_annotator3)
        vote(species1, self.other_annotator1, accept=False)

        # Make the accepting vote by the expert user
        vote(species1, self.annotator, accept=True)

        # Check the votes were applied as expected
        self.assertEqual(species1.accepted_by.count(), 1)
        self.assertEqual(species1.rejected_by.count(), 1)

        # Get the object validity
        species_obj = Species.objects.filter(id=species1.id)
        species_values = species_obj.values()

        zipped_species_querysets = list(zip(species_obj, species_values))
        annotate(zipped_species_querysets)

        self.assertEqual(zipped_species_querysets[0][1].get("status"), "VALID")

    """
    Double staff/expert rejections over acceptions should override them
    """

    def test_expert_rejections_override_acception(self):
        # Make users expert
        self.user.is_expert = True
        self.user.save()

        self.other_user1.is_expert = True
        self.other_user1.save()

        self.other_user2.is_expert = True
        self.other_user2.save()

        # Check we're using experts
        self.assertTrue(self.user.is_expert)
        self.assertTrue(self.other_user1.is_expert)
        self.assertTrue(self.other_user2.is_expert)

        # Make the rejecting votes by other annotators
        species1 = create_test_species_object(self.bbox1, "Bobcat", "WILD", self.other_annotator3)
        vote(species1, self.other_annotator2, accept=False)
        vote(species1, self.other_annotator1, accept=False)

        # Make the accepting vote by the expert user
        vote(species1, self.annotator, accept=True)

        # Check the votes were applied as expected
        self.assertEqual(species1.accepted_by.count(), 1)
        self.assertEqual(species1.rejected_by.count(), 2)

        # Get the object validity
        species_obj = Species.objects.filter(id=species1.id)
        species_values = species_obj.values()

        zipped_species_querysets = list(zip(species_obj, species_values))
        annotate(zipped_species_querysets)

        self.assertEqual(zipped_species_querysets[0][1].get("status"), "INVALID")

    """
    Correlated objects (i.e. Category, Species, or Activity) should also be invalid
    if its bounding box is invalid.
    """

    def test_invalid_bbox_correlated_objects_rejected(self):
        # Make user expert
        self.user.is_expert = True
        self.user.save()

        # Check user states
        self.assertTrue(self.user.is_expert)
        self.assertFalse(self.other_user1.is_expert)
        self.assertFalse(self.other_user1.is_staff)

        # Create the bbox and correlated object
        bbox2 = create_test_bboxes(
            test_image_object=self.test_image, test_user_object=self.other_annotator1, num_boxes=1
        )
        species1 = create_test_species_object(bbox2, "Human", "HUMAN", self.other_annotator3)

        # Cast the expert reject vote
        vote(bbox2, self.annotator, accept=False)

        # Get the bbox validity
        bbox_obj = BoundingBox.objects.filter(id=bbox2.id)
        bbox_values = bbox_obj.values()

        zipped_bbox_querysets = list(zip(bbox_obj, bbox_values))
        annotate(zipped_bbox_querysets)

        self.assertEqual(zipped_bbox_querysets[0][1].get("status"), "INVALID")

        # Get the correlated object validity
        species_obj = Species.objects.filter(id=species1.id)
        species_values = species_obj.values()

        zipped_species_querysets = list(zip(species_obj, species_values))
        annotate(zipped_species_querysets)

        self.assertEqual(zipped_species_querysets[0][1].get("status"), "INVALID")


class SkipIneligibleImagesTestCase(AnnotationFlagsTestCase):
    def setUp(self):
        super().setUp()

    """
    This was a bug caused when species was complete but category wasn't
    due to leftover boxes that had no votes. These occured on old images
    that were migrated. This checks to see if this bug's been reintroduced.
    """

    def test_category_incomplete_species_complete(self):
        # Set user to staff
        self.user.is_expert = True
        self.user.save()

        # Check we're using an expert user
        self.assertTrue(self.user.is_expert)

        # Setup objects and check flags
        bbox1 = create_test_bboxes(test_image_object=self.test_image, test_user_object=self.annotator, num_boxes=1)
        species1 = create_test_species_object(bbox1, "Mule Deer", "WILD", self.annotator)

        # Add an uncertain bbox to make the image species eligible
        bbox2 = create_test_bboxes(
            test_image_object=self.test_image, test_user_object=Annotator.objects.create(type="Bot"), num_boxes=1
        )

        self.test_image2 = create_test_image_object(self.test_upload)

        # Make sure flag conditions are correct for this test
        calculateCategoryAnnotationFlags(self.test_image)

        # Category complete is a prerequisite to species complete, set this to true temporarily to set species complete true as well
        self.test_image.category_pipeline_complete = True
        calculateSpeciesAnnotationFlags(self.test_image)
        self.test_image.category_pipeline_complete = False
        self.test_image.save()

        self.assertFalse(self.test_image.category_pipeline_complete)
        self.assertTrue(self.test_image.species_pipeline_complete)

        # Setup the queue object
        queue = {"index": 0, "images": [self.test_image.id, self.test_image2.id]}

        # The first image should be the one returned (i.e. first img wasn't skipped)
        result = skip_ineligible_images(queue_name="AnnotateSpeciesQueue", queue=queue, annotator=self.annotator)

        self.assertEqual(self.test_image.id, result.id)


class ImageUniquenessTestCase(TestCase):
    def setUp(self):
        user, email, password = create_test_user_object("Justin")
        self.user = user
        self.upload = create_test_upload_object(self)

    def test_image_not_deleted_enforces_uniqueness(self):
        create_test_image_object(self.upload, content_hash="duplicate")

        with transaction.atomic(), self.assertRaises(IntegrityError):
            create_test_image_object(self.upload, content_hash="duplicate")

        create_test_image_object(self.upload, content_hash="okay")

    def test_deleted_image_bypasses_uniqueness(self):
        image = create_test_image_object(self.upload, content_hash="duplicate")

        # Make sure the signal updates the image field
        self.assertFalse(image.deleted)

        image.upload.deleted = True
        image.upload.save()

        image = Image.objects.get(id=image.id)

        self.assertTrue(image.deleted)

        # Create new obj
        create_test_image_object(self.upload, content_hash="duplicate")

        # Test constraint still applies when undeleting
        with transaction.atomic(), self.assertRaises(IntegrityError):
            image.upload.deleted = False
            image.upload.save()


# ---------------------------------------------------------------------------
# Tests for the ingest_annotations management command helpers
# ---------------------------------------------------------------------------


def create_test_image_for_ingestion(upload, filename, content_hash):
    """Create an image with a specific filename for ingestion tests."""
    return Image.objects.create(
        upload=upload,
        dropbox_file_name=filename,
        dropbox_file_path=f"/test/{filename.lower()}",
        dropbox_file_path_display=f"/test/{filename}",
        dropbox_content_hash=content_hash,
        dropbox_file_id=f"id:{filename}",
        file_size=1024,
    )


class IngestAnnotationsBaseTestCase(TestCase):
    """Base test case with common setup for ingestion tests."""

    def setUp(self):
        user, email, password = create_test_user_object("IngestUser")
        self.user = user
        self.upload = create_test_upload_object(self)

        self.image_animal = create_test_image_for_ingestion(
            self.upload, "animal_image.jpg", "hash_animal_001"
        )
        self.image_person = create_test_image_for_ingestion(
            self.upload, "person_image.jpg", "hash_person_001"
        )


class ExtractScientificNameTestCase(TestCase):
    """Tests for the _extract_scientific_name_from_prediction helper."""

    def test_full_taxonomic_path(self):
        result = _extract_scientific_name_from_prediction(
            "mammalia;carnivora;felidae;puma;puma concolor"
        )
        self.assertEqual(result, "Puma concolor")

    def test_simple_binomial(self):
        result = _extract_scientific_name_from_prediction("lynx rufus")
        self.assertEqual(result, "Lynx rufus")

    def test_blank_prediction(self):
        result = _extract_scientific_name_from_prediction("blank")
        self.assertEqual(result, "")

    def test_empty_prediction(self):
        result = _extract_scientific_name_from_prediction("")
        self.assertEqual(result, "")

    def test_unknown_prediction(self):
        result = _extract_scientific_name_from_prediction("unknown")
        self.assertEqual(result, "")

    def test_no_cv_result(self):
        result = _extract_scientific_name_from_prediction("no_cv_result")
        self.assertEqual(result, "")


class IngestMegadetectorTestCase(IngestAnnotationsBaseTestCase):
    """Tests for the ingest_megadetector function."""

    def _make_md_data(self, detections_per_image=None):
        """Build a minimal MegaDetector output dict."""
        if detections_per_image is None:
            detections_per_image = {
                "animal_image.jpg": [{"category": "1", "conf": 0.92, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                "person_image.jpg": [{"category": "2", "conf": 0.85, "bbox": [0.2, 0.2, 0.5, 0.6]}],
            }
        return {
            "images": [
                {"file": filepath, "detections": dets}
                for filepath, dets in detections_per_image.items()
            ],
            "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"},
            "info": {"detector": "md_v5a.0.0"},
        }

    def test_dry_run_creates_no_records(self):
        data = self._make_md_data()
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=False)

        self.assertEqual(BoundingBox.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)

    def test_creates_bbox_and_category(self):
        data = self._make_md_data()
        stats = ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["bboxes_created"], 2)
        self.assertEqual(stats["categories_created"], 2)
        self.assertEqual(BoundingBox.objects.count(), 2)
        self.assertEqual(Category.objects.count(), 2)

    def test_category_names_are_correct(self):
        data = self._make_md_data()
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        animal_bbox = BoundingBox.objects.get(image=self.image_animal)
        person_bbox = BoundingBox.objects.get(image=self.image_person)

        self.assertEqual(Category.objects.get(bounding_box=animal_bbox).name, "animal")
        self.assertEqual(Category.objects.get(bounding_box=person_bbox).name, "person")

    def test_confidence_threshold_filters_detections(self):
        data = self._make_md_data(
            detections_per_image={
                "animal_image.jpg": [
                    {"category": "1", "conf": 0.95, "bbox": [0.1, 0.1, 0.3, 0.4]},
                    {"category": "1", "conf": 0.05, "bbox": [0.5, 0.5, 0.1, 0.1]},  # below threshold
                ]
            }
        )
        stats = ingest_megadetector(data, confidence_threshold=0.2, make_changes=True)

        # Only the high-confidence detection should be saved
        self.assertEqual(stats["bboxes_created"], 1)
        self.assertEqual(BoundingBox.objects.count(), 1)

    def test_image_not_found_is_counted(self):
        data = self._make_md_data(
            detections_per_image={
                "nonexistent_image.jpg": [{"category": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}]
            }
        )
        stats = ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["images_not_found"], 1)
        self.assertEqual(BoundingBox.objects.count(), 0)

    def test_idempotent_ingestion(self):
        data = self._make_md_data(
            detections_per_image={
                "animal_image.jpg": [{"category": "1", "conf": 0.92, "bbox": [0.1, 0.1, 0.3, 0.4]}]
            }
        )
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)
        stats2 = ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        # Second run should skip the existing record
        self.assertEqual(stats2["skipped_existing"], 1)
        self.assertEqual(BoundingBox.objects.count(), 1)

    def test_bot_and_annotator_created(self):
        data = self._make_md_data()
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        bot = Bot.objects.filter(name="MegaDetector").first()
        self.assertIsNotNone(bot)
        self.assertEqual(Annotator.objects.filter(type="bot", bot=bot).count(), 1)

    def test_vehicle_category(self):
        data = self._make_md_data(
            detections_per_image={
                "animal_image.jpg": [{"category": "3", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}]
            }
        )
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        bbox = BoundingBox.objects.first()
        self.assertIsNotNone(bbox)
        self.assertEqual(Category.objects.get(bounding_box=bbox).name, "vehicle")

    def test_bbox_coordinates_stored_correctly(self):
        data = self._make_md_data(
            detections_per_image={
                "animal_image.jpg": [{"category": "1", "conf": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4]}]
            }
        )
        ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        bbox = BoundingBox.objects.first()
        self.assertAlmostEqual(bbox.x, 0.1, places=5)
        self.assertAlmostEqual(bbox.y, 0.2, places=5)
        self.assertAlmostEqual(bbox.w, 0.3, places=5)
        self.assertAlmostEqual(bbox.h, 0.4, places=5)

    def test_filename_match_with_directory_prefix(self):
        # JSON has a full path; DB only stores the filename
        data = self._make_md_data(
            detections_per_image={
                "some/nested/path/animal_image.jpg": [
                    {"category": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.3]}
                ]
            }
        )
        stats = ingest_megadetector(data, confidence_threshold=0.1, make_changes=True)

        # Should match via filename fallback
        self.assertEqual(stats["images_found"], 1)
        self.assertEqual(stats["bboxes_created"], 1)


class IngestSpeciesNetTestCase(IngestAnnotationsBaseTestCase):
    """Tests for the ingest_speciesnet function."""

    def setUp(self):
        super().setUp()
        # Create a SpeciesName that SpeciesNet can match
        self.puma_species = SpeciesName.objects.get_or_create(
            name="Puma",
            defaults={"scientific_name": "Puma concolor", "species_group": "WILD"},
        )[0]
        if not self.puma_species.scientific_name:
            self.puma_species.scientific_name = "Puma concolor"
            self.puma_species.save()

    def _make_sn_data(self, predictions=None):
        """Build a minimal SpeciesNet output dict (dict-keyed format)."""
        if predictions is None:
            predictions = {
                "animal_image.jpg": {
                    "detections": [{"label": "1", "conf": 0.93, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "mammalia;carnivora;felidae;puma;puma concolor",
                    "score": 0.85,
                }
            }
        return {"predictions": predictions, "info": {"model": "speciesnet_v4.0.0a"}}

    def test_dry_run_creates_no_records(self):
        data = self._make_sn_data()
        ingest_speciesnet(data, confidence_threshold=0.1, make_changes=False)

        self.assertEqual(BoundingBox.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(Species.objects.count(), 0)

    def test_creates_bbox_category_and_species(self):
        data = self._make_sn_data()
        stats = ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["bboxes_created"], 1)
        self.assertEqual(stats["categories_created"], 1)
        self.assertEqual(stats["species_created"], 1)
        self.assertEqual(BoundingBox.objects.count(), 1)
        self.assertEqual(Category.objects.count(), 1)
        self.assertEqual(Species.objects.count(), 1)

    def test_species_linked_to_correct_species_name(self):
        data = self._make_sn_data()
        ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        species_obj = Species.objects.first()
        self.assertIsNotNone(species_obj)
        self.assertEqual(species_obj.name.scientific_name, "Puma concolor")

    def test_blank_prediction_creates_no_species(self):
        data = self._make_sn_data(
            predictions={
                "animal_image.jpg": {
                    "detections": [{"label": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "blank",
                    "score": 0.99,
                }
            }
        )
        stats = ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["bboxes_created"], 1)
        self.assertEqual(stats["species_created"], 0)
        self.assertEqual(Species.objects.count(), 0)

    def test_unmatched_species_is_counted(self):
        data = self._make_sn_data(
            predictions={
                "animal_image.jpg": {
                    "detections": [{"label": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "mammalia;rodentia;sciuridae;sciurus;sciurus carolinensis",
                    "score": 0.9,
                }
            }
        )
        stats = ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["species_not_matched"], 1)
        self.assertEqual(Species.objects.count(), 0)

    def test_person_detection_creates_no_species(self):
        data = self._make_sn_data(
            predictions={
                "person_image.jpg": {
                    "detections": [{"label": "2", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "mammalia;carnivora;felidae;puma;puma concolor",
                    "score": 0.9,
                }
            }
        )
        ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        # Category should be 'person', not animal, so no Species created
        self.assertEqual(Category.objects.filter(name="person").count(), 1)
        self.assertEqual(Species.objects.count(), 0)

    def test_list_format_predictions(self):
        """SpeciesNet can also output predictions as a list."""
        data = {
            "predictions": [
                {
                    "filepath": "animal_image.jpg",
                    "detections": [{"label": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "mammalia;carnivora;felidae;puma;puma concolor",
                    "score": 0.85,
                }
            ],
            "info": {"model": "speciesnet_v4.0.0a"},
        }
        stats = ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats["bboxes_created"], 1)
        self.assertEqual(stats["species_created"], 1)

    def test_idempotent_ingestion(self):
        data = self._make_sn_data()
        ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)
        stats2 = ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        self.assertEqual(stats2["skipped_existing"], 1)
        self.assertEqual(BoundingBox.objects.count(), 1)
        self.assertEqual(Species.objects.count(), 1)

    def test_species_confidence_below_threshold_creates_no_species(self):
        data = self._make_sn_data(
            predictions={
                "animal_image.jpg": {
                    "detections": [{"label": "1", "conf": 0.9, "bbox": [0.1, 0.1, 0.3, 0.4]}],
                    "prediction": "mammalia;carnivora;felidae;puma;puma concolor",
                    "score": 0.05,  # below threshold
                }
            }
        )
        stats = ingest_speciesnet(data, confidence_threshold=0.2, make_changes=True)

        self.assertEqual(stats["bboxes_created"], 1)
        self.assertEqual(stats["species_created"], 0)
        self.assertEqual(Species.objects.count(), 0)

    def test_bot_and_annotator_created(self):
        data = self._make_sn_data()
        ingest_speciesnet(data, confidence_threshold=0.1, make_changes=True)

        bot = Bot.objects.filter(name="SpeciesNet").first()
        self.assertIsNotNone(bot)
        self.assertEqual(Annotator.objects.filter(type="bot", bot=bot).count(), 1)
