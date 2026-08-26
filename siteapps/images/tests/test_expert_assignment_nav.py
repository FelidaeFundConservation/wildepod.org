"""
Tests for the "Assigned to me" nav item, which is how an expert learns work has been
assigned to them.

Nothing notifies them and the only link to the searched queue is on the staff search page, so
until assignment surfaces in the tab bar this count is the whole of the answer.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse
from images.context_processors import expert_assignment
from images.models import Annotator, CameraStationAction, Image, ImageQueue, Upload
from locations.models import Area, CameraStation, County, MacroSite, MicroSite

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(email="navstaff@example.com", password="testpass123", is_staff=True)


@pytest.fixture
def client_logged_in(staff_user):
    client = Client()
    client.force_login(staff_user)

    return client


@pytest.fixture
def expert(db):
    return User.objects.create_user(
        email="navexpert@example.com", password="testpass123", name="Ellie Expert", is_expert=True
    )


@pytest.fixture
def upload(db, staff_user):
    from django.utils import timezone

    area = Area.objects.create(name="Nav Area")
    county = County.objects.create(name="Nav County", area=area)
    macro_site = MacroSite.objects.create(name="Nav Macro Site", county=county)
    micro_site = MicroSite.objects.create(name="Nav Micro Site", macro_site=macro_site)
    camera_station = CameraStation.objects.create(
        station_id="NAV001",
        micro_site=micro_site,
        latitude=27.5,
        longitude=89.5,
        date_deployed=timezone.now().date(),
    )
    action, _ = CameraStationAction.objects.get_or_create(action="DEPLOY")

    return Upload.objects.create(
        camera_station=camera_station,
        volunteer=staff_user,
        date_retrieved=timezone.now(),
        last_action=action,
        dropbox_folder_name="nav_folder",
        dropbox_folder_path="/nav/folder",
        upload_method="E",
    )


def make_image(upload, name):
    from django.utils import timezone

    return Image.objects.create(
        upload=upload,
        dropbox_file_name=f"{name}.jpg",
        dropbox_file_path=f"/test/{name}.jpg",
        dropbox_file_path_display=f"/test/{name}.jpg",
        dropbox_content_hash=f"hash_{name}",
        dropbox_file_id=f"file_id_{name}",
        file_size=1024,
        trigger_timestamp=timezone.now(),
        thumbnail_gcloud_path=f"test/{name}_thumb.jpg",
    )


def assign(client, expert, images):
    """Through the bulk endpoint, so this exercises the path staff actually use."""
    return client.post(
        reverse("images:bulk_image_action"),
        {
            "action": "assign_expert",
            "image_ids[]": [str(image.id) for image in images],
            "expert_id": str(expert.id),
        },
    )


@pytest.mark.django_db
class TestExpertAssignmentNav:
    def nav_for(self, user):
        client = Client()
        client.force_login(user)

        return client.get(reverse("home:index")).content.decode()

    def count_for(self, user):
        request = RequestFactory().get("/")
        request.user = user

        return expert_assignment(request).get("assigned_image_count")

    def test_a_volunteer_is_not_offered_the_queue(self, db):
        """The processor runs on every page for every user, so it has to cost nothing and say
        nothing for the people it is not for."""
        volunteer = User.objects.create_user(email="navvolunteer@example.com", password="testpass123")

        assert self.count_for(volunteer) is None
        assert "Assigned to me" not in self.nav_for(volunteer)

    def test_an_expert_with_nothing_assigned_gets_no_link(self, expert):
        """Not merely cosmetic: with no queue assigned the same URL falls through to ordinary
        volunteer images, so a link here would promise assigned work and serve something else."""
        assert self.count_for(expert) == 0
        assert "Assigned to me" not in self.nav_for(expert)

    def test_bulk_assigned_images_show_up_in_the_expert_nav(self, client_logged_in, upload, expert):
        assign(client_logged_in, expert, [make_image(upload, f"assigned_{index}") for index in range(3)])

        assert self.count_for(expert) == 3

        nav = self.nav_for(expert)
        assert "Assigned to me" in nav
        assert reverse("images:searched_annotate_species") in nav

    def test_the_count_is_what_is_left_not_what_was_assigned(self, client_logged_in, upload, expert):
        """Read against the queue cursor. A count that never moved would still be claiming
        three the day after the expert finished all three."""
        images = [make_image(upload, f"working_{index}") for index in range(3)]
        assign(client_logged_in, expert, images)

        queue = ImageQueue.objects.get(assigned_to__human=expert)
        queue.advance_past(images[0].id)

        assert self.count_for(expert) == 2

        queue.advance_past(images[2].id)

        assert self.count_for(expert) == 0
        assert "Assigned to me" not in self.nav_for(expert)

    def test_a_second_assignment_adds_to_the_count(self, client_logged_in, upload, expert):
        assign(client_logged_in, expert, [make_image(upload, "batch_one")])
        assign(client_logged_in, expert, [make_image(upload, "batch_two")])

        assert self.count_for(expert) == 2

    def test_an_automatically_precomputed_queue_is_not_assigned_work(self, upload, expert):
        """Annotating anything assigns the annotator a precomputed queue, which nobody built
        for them. Counting those would put a number in the nav that no staff member chose."""
        annotator, _ = Annotator.objects.get_or_create(type="human", human=expert)
        queue = ImageQueue.objects.create(pipeline_name="SPECIES", assigned_to=annotator)
        queue.images.add(make_image(upload, "precomputed"))

        assert queue.image_order == []
        assert self.count_for(expert) == 0

    def test_one_expert_does_not_see_anothers_work(self, client_logged_in, upload, expert):
        other = User.objects.create_user(
            email="navother@example.com", password="testpass123", is_expert=True
        )

        assign(client_logged_in, expert, [make_image(upload, "not_yours")])

        assert self.count_for(other) == 0
