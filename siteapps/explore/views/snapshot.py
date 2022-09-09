import csv
import logging
import threading
import zipfile
from io import BytesIO, StringIO

from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import File as DjangoFile
from django.shortcuts import redirect
from django.urls.base import reverse_lazy
from django.views.generic import FormView, ListView
from explore.forms import CreateSnapshotForm
from explore.models import Snapshot
from images.models import Image
from locations.models import CameraStation

MAX_VOTES_PER_IMAGE = 2


def export_camera_station_data(archive_file):
    """Hacky function to export camera station data to a csv file"""
    with StringIO() as csv_file:
        csv_writer = csv.writer(csv_file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow(
            [
                "camera_station_id",
                "latitude",
                "longitude",
                "micro_site",
                "macro_site",
                "county",
                "area",
                "elevation",
                "elevation_units",
                "habitat_type",
                "habitat_notes",
                "land_use_type",
                "trail_type",
                "trail_surface",
                "felidae_camera",
                "external_camera",
                "date_deployed",
                "date_last_checked",
                "date_to_be_checked",
                "date_taken_down",
                "boxed",
                "padlock_type",
                "python_lock",
                "linked_volunteers",
                "comments",
            ]
        )

        # Get all camera stations
        camera_stations = CameraStation.objects.all()

        for camera_station in camera_stations:
            csv_writer.writerow(
                [
                    camera_station.station_id,
                    camera_station.latitude,
                    camera_station.longitude,
                    camera_station.micro_site,
                    camera_station.micro_site.macro_site,
                    camera_station.micro_site.macro_site.county,
                    camera_station.micro_site.macro_site.county.area,
                    camera_station.elevation,
                    camera_station.elevation_unit,
                    " | ".join([habitat_type.name for habitat_type in camera_station.habitat_types.all()]),
                    camera_station.habitat_notes,
                    " | ".join([land_use_type.name for land_use_type in camera_station.land_use_type.all()]),
                    camera_station.trail_type,
                    camera_station.trail_surface,
                    camera_station.camera,
                    camera_station.external_camera,
                    camera_station.date_deployed,
                    camera_station.date_last_checked,
                    camera_station.date_to_be_checked,
                    camera_station.date_taken_down,
                    camera_station.boxed,
                    camera_station.padlock,
                    camera_station.python_lock,
                    " | ".join([volunteer.name for volunteer in camera_station.volunteer.all()]),
                    camera_station.comments,
                ]
            )
        logging.info("Finished creating a csv file for camera stations")
        archive_file.writestr("camera_stations.tsv", csv_file.getvalue())
        logging.info("Finished writing camera station csv to archive")


def export_image_data(archive_file, images):
    """Hacky function to export camera station data to a csv file"""
    with StringIO() as csv_file:
        csv_writer = csv.writer(csv_file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow(
            [
                "image_id",
                "content_hash",
                "filename",
                "thumbnail",
                "dropbox_link",
                "trigger_timestamp",
                "exif_latitude",
                "exif_longitude",
                "is_video",
                "camera_station_id",
                "micro_site",
                "macro_site",
                "date_retrieved",
                "volunteer",
                "upload_folder",
                "social_media_worthy_vote_count",
                "blank_checked_by",
                "detected_objects",
                "validated_objects",
                "uncertain_objects",
                "objects",
                "species_checked_by",
                "validated_species",
                "uncertain_species",
                "species",
            ]
        )

        for i, image in enumerate(images):
            valid_bounding_boxes = image.boundingbox_set.valid()
            uncertain_bounding_boxes = image.boundingbox_set.uncertain()
            valid_or_uncertain_bounding_boxes = image.boundingbox_set.valid_or_uncertain()

            csv_writer.writerow(
                [
                    image.id,
                    image.dropbox_content_hash,
                    image.dropbox_file_name,
                    f"""https://storage.googleapis.com/{settings.GS_BUCKET_NAME}/media/{image.thumbnail_gcloud_path}""",
                    f"""{settings.DROPBOX_URL_PREFIX}/{image.dropbox_file_path}""",
                    image.trigger_timestamp,
                    image.latitude,
                    image.longitude,
                    image.is_video,
                    image.upload.camera_station.station_id,
                    image.upload.camera_station.micro_site,
                    image.upload.camera_station.micro_site.macro_site,
                    image.upload.date_retrieved,
                    image.upload.volunteer,
                    f"""{settings.DROPBOX_URL_PREFIX}/{image.upload.dropbox_folder_path}""",
                    image.social_media_worthy,
                    len(image.bbox_checked_by.all()),
                    len(valid_or_uncertain_bounding_boxes),
                    len(valid_bounding_boxes),
                    len(uncertain_bounding_boxes),
                    " | ".join([bbox.category_set.first().name for bbox in valid_bounding_boxes]),
                    len(image.species_checked_by.all()),
                    len([True for bbox in valid_bounding_boxes if bbox.species_set.valid().exists()]),
                    len([True for bbox in valid_bounding_boxes if bbox.species_set.uncertain().exists()]),
                    " | ".join(
                        [
                            bbox.species_set.first().name.name
                            for bbox in valid_bounding_boxes
                            if bbox.species_set.first()
                        ]
                    ),
                ]
            )

            if i % 100 == 0:
                logging.info(f"Finished {i}/{len(images)} images")

        logging.info("Finished creating a csv file for images")
        archive_file.writestr("images.tsv", csv_file.getvalue())
        logging.info("Finished writing image csv to archive")


def create_snapshot(cleaned_form_data, user):
    """This is a hacky function to create a snapshot inside a thread and update the object when done"""
    # First, use the form data to retrieve a filtered set of images
    filterset = {}
    start_date = cleaned_form_data["start_date"]
    if start_date:
        filterset["trigger_timestamp__gte"] = start_date
    end_date = cleaned_form_data["end_date"]
    if end_date:
        filterset["trigger_timestamp__lte"] = end_date
    macrosites = cleaned_form_data["macrosites"]
    if macrosites:
        filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
    # annotated_only = cleaned_form_data["annotated_only"]

    images = Image.objects.annotated().filter(**filterset)

    # Next, create a snapshot object
    snapshot = Snapshot.objects.create(
        volunteer=user,
        start_date=start_date,
        end_date=end_date,
        # annotated_only=annotated_only,
    )
    snapshot.macrosites.set(macrosites)

    try:
        # Create an archive file to house all the csvs
        zipped_file = BytesIO()
        with zipfile.ZipFile(zipped_file, "w") as archive_file:

            # Export a multitude of csvs
            # Start with camera stations themselves
            export_camera_station_data(archive_file)

            # Then export image data
            export_image_data(archive_file, images)

            # Create a Django file object for this
            archive_obj = DjangoFile(zipped_file, name=f"{snapshot}.zip")

        logging.info("Finished creating archive file")
        snapshot.data = archive_obj
        snapshot.status = "done"
    except Exception as e:
        snapshot.status = "failed"
        logging.error(f"Error while creating snapshot: {e}")
    snapshot.save()


class SnapshotCreateView(LoginRequiredMixin, StaffuserRequiredMixin, FormView):
    login_url = settings.LOGIN_URL
    template_name = "explore/snapshots/create.html"
    form_class = CreateSnapshotForm
    success_url = reverse_lazy("explore:data_snapshots")

    def post(self, request, *args, **kwargs):
        form = CreateSnapshotForm(request.POST)

        if form.is_valid():
            logging.info(f"Starting a thread to create a snapshot with filters - {form.cleaned_data}")
            # Create a thread to process the upload
            thread = threading.Thread(target=create_snapshot, args=[form.cleaned_data, self.request.user])
            # Move it to the background
            thread.setDaemon(True)
            # Start running the thread
            thread.start()

        return redirect("explore:data_snapshots")


class SnapshotListView(LoginRequiredMixin, StaffuserRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    template_name = "explore/snapshots/list.html"
    model = Snapshot
