import csv
import gc
import json
import logging
import threading
import zipfile
from datetime import datetime
from io import BytesIO, StringIO
from itertools import groupby

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import File as DjangoFile
from django.core.paginator import Paginator
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from explore.models import Snapshot
from images.models import Image
from locations.models import CameraStation, MacroSite
from users.models import User


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

        index = 0
        page_size = 1000
        paginator = Paginator(images, page_size)
        for page_number in paginator.page_range:
            logging.info(f"Processing page {page_number} of {paginator.num_pages}. Image index : {index}")
            page = paginator.get_page(page_number)

            for image in page:
                valid_bounding_boxes = image.boundingbox_set.valid()
                uncertain_bounding_boxes = image.boundingbox_set.uncertain()
                valid_or_uncertain_bounding_boxes = image.boundingbox_set.valid_or_uncertain()

                # We need to separate out the categories and the species when there are multiple annotations for the same image
                # If there are multiple catrgories/species, we will generate multiple rows in the output per each group.
                if valid_bounding_boxes:
                    # Use groupby and a lambda function to split the bounding boxes into subgroups based on the category name
                    category_groups = groupby(valid_bounding_boxes, lambda x: x.category_set.first().name)
                    for category_name, bbox_categories in category_groups:
                        # Use groupby and a lambda function to split the bounding boxes into subgroups based on the species name
                        species_groups = groupby(
                            bbox_categories,
                            lambda x: x.species_set.first().name.name if x.species_set.first() else "",
                        )
                        for species_name, bbox_species in species_groups:
                            write_row(
                                csv_writer,
                                image,
                                category_name,
                                species_name,
                                list(bbox_species),
                                uncertain_bounding_boxes,
                                valid_or_uncertain_bounding_boxes,
                            )
                else:
                    write_row(
                        csv_writer,
                        image,
                        "",
                        "",
                        valid_bounding_boxes,
                        uncertain_bounding_boxes,
                        valid_or_uncertain_bounding_boxes,
                    )

                if index % 1000 == 0:
                    logging.info(f"Finished {index} images")

                index += 1
            # Clear django cache and garbage collect to avoid memory issues
            cache.clear()
            gc.collect()

        logging.info("Finished creating a csv file for images")
        archive_file.writestr("images.tsv", csv_file.getvalue())
        logging.info("Finished writing image csv to archive")


def write_row(
    csv_writer,
    image,
    category_name,
    species_name,
    valid_bounding_boxes,
    uncertain_bounding_boxes,
    valid_or_uncertain_bounding_boxes,
):
    output_list = [
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
        category_name,
        len(image.species_checked_by.all()),
        len([True for bbox in valid_bounding_boxes if bbox.species_set.valid().exists()]),
        len([True for bbox in valid_bounding_boxes if bbox.species_set.uncertain().exists()]),
        species_name,
    ]
    csv_writer.writerow(output_list)


def create_snapshot(data):
    """This is a hacky function to create a snapshot inside a thread and update the object when done"""
    # Fetch the volunteer from the request data using the primary key
    user_pk = data.get("user")
    volunteer = None
    try:
        volunteer = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        logging.error(f"User with pk {user_pk} does not exist!")
        return

    # First, use the form data to retrieve a filtered set of images
    filterset = {}
    start_date = data.get("start_date")
    if start_date:
        filterset["trigger_timestamp__gte"] = datetime.strptime(start_date, settings.EXPORT_DATE_FORMAT)
    end_date = data.get("end_date")
    if end_date:
        filterset["trigger_timestamp__lte"] = datetime.strptime(end_date, settings.EXPORT_DATE_FORMAT)

    # Fetch the macrosites from the request data using the primary keys
    macrosites_pks = data.get("macrosites", [])
    macrosites = None
    if macrosites_pks:
        macrosites = MacroSite.objects.filter(pk__in=macrosites_pks)
        filterset["upload__camera_station__micro_site__macro_site__in"] = macrosites
    # annotated_only = cleaned_form_data["annotated_only"]

    images = Image.objects.annotated().filter(**filterset).order_by("trigger_timestamp")

    # Next, create a snapshot object
    snapshot = Snapshot.objects.create(
        volunteer=volunteer,
        start_date=start_date,
        end_date=end_date,
        # annotated_only=annotated_only,
    )
    if macrosites:
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


def portal_export(macrosite_param=None, station_id_param=None, start_date_param=None, end_date_param=None):
    """Wrapper function for calling the PostgreSQL stored procedure"""
    with connection.cursor() as cursor:
        cursor.callproc("portal_export", (macrosite_param, station_id_param, 
                                start_date_param, end_date_param))
        results = cursor.fetchall()
        return results               


def export_image_data_sql(archive_file, images):
    """Function to export image data to a csv file"""
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

        for image in images:
            csv_writer.writerow(image)

        logging.info("Finished creating a csv file for images")
        archive_file.writestr("images.tsv", csv_file.getvalue())
        logging.info("Finished writing image csv to archive")


def create_snapshot_sql(data):
    """This is a hacky function to create a snapshot inside a thread and update the object when done"""
    # Fetch the volunteer from the request data using the primary key
    user_pk = data.get("user")
    volunteer = None
    try:
        volunteer = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        logging.error(f"User with pk {user_pk} does not exist!")
        return

    # First, use the form data to retrieve a filtered set of images
    filterset = {}
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    # Fetch the macrosites from the request data using the primary keys
    macrosites_pks = data.get("macrosites", [])
    macrosites = None
    macrosites_str = None
    if macrosites_pks:
        macrosites = MacroSite.objects.filter(pk__in=macrosites_pks)
        macrosites_str = str(macrosites[0])

    images = portal_export(macrosite_param=macrosites_str, 
                           start_date_param=start_date,
                           end_date_param=end_date)
    
    # Next, create a snapshot object
    snapshot = Snapshot.objects.create(
        volunteer=volunteer,
        start_date=start_date,
        end_date=end_date,
    )
    if macrosites:
        snapshot.macrosites.set(macrosites)

    try:
        # Create an archive file to house all the csvs
        zipped_file = BytesIO()
        with zipfile.ZipFile(zipped_file, "w") as archive_file:
            # Export image data
            export_image_data_sql(archive_file, images)

            # Create a Django file object for this
            archive_obj = DjangoFile(zipped_file, name=f"{snapshot}.zip")

        logging.info("Finished creating archive file")
        snapshot.data = archive_obj
        snapshot.status = "done"
    except Exception as e:
        snapshot.status = "failed"
        logging.error(f"Error while creating snapshot: {e}")
    snapshot.save()


def start_export(data):
    logging.info("Direct export triggered")
    logging.info(f"Starting a thread to create a snapshot with filters - {data}")
    # Create a thread to process the upload
    thread = threading.Thread(target=create_snapshot_sql, args=[data])
    # Start running the thread
    thread.start()

    return JsonResponse({"message": "Success"})


# We can't use CSRF token authentication here because this is a different appengine instance.
# In addition to obfuscating the URL, we can also use a secret key to authenticate the request
@method_decorator(csrf_exempt, name="dispatch")
class ExportStartView(View):
    def post(self, request):
        logging.info(f"Received request to start export : {request.body}")
        undecoded_data = request.body.decode()
        data = json.loads(undecoded_data)

        logging.info(f"Starting a thread to create a snapshot with filters - {data}")
        # Create a thread to process the upload
        thread = threading.Thread(target=create_snapshot, args=[data])
        # Start running the thread
        thread.start()

        return JsonResponse({"message": "Success"})
