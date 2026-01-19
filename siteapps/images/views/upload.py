import json
import logging
import threading
from datetime import datetime, timedelta

import pytz
from braces.views import StaffuserRequiredMixin
from dateutil.relativedelta import relativedelta
from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.http.response import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.views.generic.base import TemplateView, View
from images.forms import TimeCorrectionForm, UploadCompleteForm, UploadForm, get_daylight_savings_date
from images.models import Annotator, BoundingBox, Image, TimeCorrection, Upload
from images.processors import clone_data_sheet, process_upload, setup_dropbox_paths
from images.processors.upload import get_dropbox_item_count
from locations.models import CameraStation, MacroSite, MicroSite
from users.models import User

# Pagination size for images displayed for the upload detail page
IMAGE_PAGINATION_LIMIT = 24


# Views
# ------------------------------------------------------------------------------
class UploadCreateView(LoginRequiredMixin, CreateView):
    model = Upload
    form_class = UploadForm
    login_url = settings.LOGIN_URL
    template_name = "images/upload/create.html"

    def form_valid(self, form):
        years = form.cleaned_data.get("time_correction_years") or 0
        months = form.cleaned_data.get("time_correction_months") or 0
        days = form.cleaned_data.get("time_correction_days") or 0
        hours = form.cleaned_data.get("time_correction_hours") or 0
        minutes = form.cleaned_data.get("time_correction_minutes") or 0

        daylight_savings = form.cleaned_data.get("daylight_savings_correction") or None

        start_date = form.cleaned_data.get("start_date") or None
        end_date = form.cleaned_data.get("end_date") or None

        data_sheet = form.cleaned_data.get("data_sheet") or None

        upload_obj = form.save(commit=False)

        # Handles creating folder, cloning data sheet, setting folder paths
        setup_dropbox_paths(upload_obj, data_sheet)

        # Construct the time correction object to assign to the upload
        if not (years == months == days == hours == minutes == 0 and daylight_savings is None):
            time_correction, created = TimeCorrection.objects.get_or_create(upload__id=upload_obj.id)

            time_correction.years = years
            time_correction.months = months
            time_correction.days = days
            time_correction.hours = hours
            time_correction.minutes = minutes

            time_correction.start_date = start_date
            time_correction.end_date = end_date

            time_correction.daylight_savings = daylight_savings

            time_correction.save()

            upload_obj.time_correction = time_correction
            upload_obj.save()

            logging.info(f"Saved time correction information for upload {upload_obj.id}.")
        else:
            logging.info(f"No time correction information entered for upload {upload_obj.id}.")

        return super(UploadCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("images:complete_upload", args=(self.object.id,))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["images"] = get_preview_images("TEST")

        return context


class UploadDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = False
        reason = None

        upload_id = request.POST.get("upload_id")
        upload_obj = Upload.objects.get(id=upload_id)

        if self.request.user != upload_obj.volunteer and not (
            self.request.user.is_staff or self.request.user.is_superuser
        ):
            reason = "User does not have permission to delete or recover this upload."
        else:
            upload_obj.deleted = not upload_obj.deleted
            upload_obj.save()

            success = True

        return JsonResponse({"success": success, "reason": reason})


def filter_uploads(context, self):
    context["macrosites"] = MacroSite.objects.all()
    context["microsites"] = MicroSite.objects.all()
    context["camera_stations"] = CameraStation.objects.all()

    query_kwargs = {}

    # Query volunteers
    context["volunteers"] = User.objects.all()

    volunteer = self.request.GET.get("volunteer")
    volunteer = None if volunteer == "" else volunteer
    volunteer = User.objects.get(name=volunteer) if volunteer else None

    if volunteer:
        query_kwargs["volunteer"] = volunteer

    # Query macrosites
    macrosite = self.request.GET.get("macrosite")
    macrosite = None if macrosite == "" else macrosite
    macrosite = MacroSite.objects.get(name=macrosite) if macrosite else None

    if macrosite:
        query_kwargs["camera_station__micro_site__macro_site"] = macrosite

    # Query microsite
    microsite = self.request.GET.get("microsite")
    microsite = None if microsite == "" else microsite
    microsite = MicroSite.objects.get(name=microsite) if microsite else None

    if microsite:
        query_kwargs["camera_station__micro_site"] = microsite

    # Query camera station
    camera_station = self.request.GET.get("camera_station")
    camera_station = None if camera_station == "" else camera_station
    camera_station = CameraStation.objects.get(station_id=camera_station) if camera_station else None

    if camera_station:
        query_kwargs["camera_station"] = camera_station

    # Query timerange
    start_date = self.request.GET.get("start_date")
    end_date = self.request.GET.get("end_date")

    if start_date:
        query_kwargs["date_retrieved__gte"] = start_date
    if end_date:
        query_kwargs["date_retrieved__lt"] = end_date

    # Filter results
    context["num_completed"] = context["object_list"].count()
    context["object_list"] = (
        context["object_list"].filter(**query_kwargs).order_by("-created")
        if len(query_kwargs) > 0
        else context["object_list"].order_by("-created")
    )


class UploadListView(LoginRequiredMixin, ListView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/list.html"

    # Staff can access all uploads across all users.
    # Non-staff users can see only their uploads
    def get_queryset(self):
        if self.request.user.is_staff or self.request.user.is_superuser:
            return super().get_queryset()
        else:
            return super().get_queryset().filter(volunteer=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX

        # Initialize upload image counts
        for upload in Upload.objects.filter(img_count=0):
            upload.img_count = upload.images.count()
            upload.save()

        # Get macrosite, microsite, and station info,
        # and filter based on previous submission's arguments
        filter_uploads(context, self)

        if self.request.user.is_staff or self.request.user.is_superuser:
            context["pending"] = Upload.objects.filter(upload_complete=False).order_by("-created")
            context["processing"] = Upload.objects.filter(upload_complete=True, processed=False).order_by("-created")

        else:
            context["pending"] = Upload.objects.filter(upload_complete=False, volunteer=self.request.user).order_by(
                "-created"
            )
            context["processing"] = Upload.objects.filter(
                upload_complete=True, processed=False, volunteer=self.request.user
            ).order_by("-created")
            context["object_list"] = (
                context["object_list"]
                .filter(upload_complete=True, processed=True, volunteer=self.request.user)
                .order_by("-created")
            )

        context["num_pending"] = context["pending"].count()
        context["num_processing"] = context["processing"].count()

        paginator = Paginator(context["object_list"], 99)
        page_number = self.request.GET.get("page")
        context["object_list"] = paginator.get_page(page_number)

        return context


class UploadCompleteView(LoginRequiredMixin, UpdateView):
    model = Upload
    form_class = UploadCompleteForm
    login_url = settings.LOGIN_URL
    template_name = "images/upload/complete.html"

    # Override post method to trigger a cloud task to process the upload
    def post(self, request, *args, **kwargs):
        # Process upload only if "upload_complete" was checked in the form
        if request.POST.get("upload_complete"):
            logging.info(
                f"Upload '{self.get_object().id}' marked as complete by the {self.request.user.name}. Starting a thread to process the upload.."
            )
            # Create a thread to process the upload
            thread = threading.Thread(target=process_upload, args=[self.get_object().id])
            # Set the name of the thread to the upload id and the function
            # This will be used to deduplicate process-upload thread runs
            thread.name = f"process_upload--{self.get_object().id}"
            # Move it to the background
            thread.setDaemon(True)
            # Start running the thread
            thread.start()

        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("images:list_uploads")


class UploadDetailView(LoginRequiredMixin, DetailView):
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        # Get valid annotations for this image
        images = self.get_object().images.all()
        paginator = Paginator(images, IMAGE_PAGINATION_LIMIT)
        page_number = self.request.GET.get("page")
        paged_images = paginator.get_page(page_number)
        # TODO: Clean this up
        context["paged_images"] = paged_images
        context["paged_images_w_boxes"] = [
            [image_obj, BoundingBox.objects.valid_or_uncertain().filter(image=image_obj)] for image_obj in paged_images
        ]

        return context


# TODO: Clean up this code
class UploadStatusView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        upload_ids = request.POST.get("upload_ids", "[]")
        upload_ids = json.loads(upload_ids)
        upload_statuses = {}
        for upload_id in upload_ids:
            try:
                upload = Upload.objects.get(id=upload_id)
                total_images = get_dropbox_item_count(upload_id)
                processed_images = upload.images.filter(processed=True).count()
                upload_statuses[upload_id] = {
                    "valid": True,
                    "total_images": total_images,
                    "processed_images": processed_images,
                }
            except ObjectDoesNotExist:
                upload_statuses[upload_id] = {
                    "valid": False,
                    "total_images": 0,
                    "processed_images": 0,
                }
        return JsonResponse({"success": True, "upload_statuses": upload_statuses})


# TODO: This view is a hack to manually retrigger the processing of an upload
# Upload processing threads can get killed when GCP decides to kill and instance when it gets no active http requests
# Ideally, move this to a cloud run instead of a thread within app engine
class UploadResumeProcessingView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        logging.info("Manually triggered to process crashed uploads")
        # First get all uploads that are already being processed by threads
        uploads_currently_being_processed = {
            thread.name.split("--")[-1] for thread in threading.enumerate() if "process_upload" in thread.name
        }
        # TODO: Rewrite this
        # Only trigger this IF there are no uploads currently being processed
        if not uploads_currently_being_processed:
            logging.info(f"{len(uploads_currently_being_processed)} uploads currently being processed")
            pending_uploads = [
                upload
                for upload in Upload.objects.filter(upload_complete=True, processed=False)
                if str(upload.id) not in uploads_currently_being_processed
            ]
            logging.info(f"{len(pending_uploads)} uploads crashed without being fully processed")
            # For each completed upload that isn't processed
            for upload in pending_uploads:
                # Create a thread to process the upload
                thread = threading.Thread(target=process_upload, args=[upload.id])
                # Set the name of the thread to the upload id and the function
                # This will be used to deduplicate process-upload thread runs
                thread.name = f"process_upload--{upload.id}"
                # Move it to the background
                thread.setDaemon(True)
                # Start running the thread
                thread.start()
                # TODO: Fix this hack
                # Break out after the first one to reduce load temporarily
                break
        else:
            logging.info(f"{len(uploads_currently_being_processed)} uploads currently being processed")

        return JsonResponse({"success": True})


def get_preview_images(upload_id):
    MAX_RESULTS = 20
    image_list = []

    # If no images in upload, sample test images
    if upload_id == "TEST":
        march_dates = [datetime(datetime.now().year, 3, day) for day in [1, 4, 7, 10, 13, 16, 19, 22, 25, 28]]
        november_dates = [datetime(datetime.now().year, 11, day) for day in [1, 4, 7, 10, 13, 16, 19, 22, 25, 28]]

        all_dates = march_dates + november_dates

        for i, date in enumerate(all_dates):
            incremented_time = date + timedelta(hours=i, minutes=7 * i)
            image_list.append({"id": f"{i}00", "trigger_time": incremented_time, "new_time": None})

        return image_list

    # Else, get an even distribution of images from specified set
    upload_obj = Upload.objects.get(id=upload_id)
    total_images = upload_obj.images.all().count()
    step_value = max(1, total_images // MAX_RESULTS)

    for image in upload_obj.images.all()[::step_value]:
        image_list.append({"id": image.id, "trigger_time": image.trigger_timestamp, "new_time": None})

    return image_list


class TimeCorrectionCreateView(LoginRequiredMixin, CreateView):
    model = TimeCorrection
    form_class = TimeCorrectionForm
    login_url = settings.LOGIN_URL
    template_name = "images/upload/create_time_correction.html"

    def form_valid(self, form):
        upload = Upload.objects.get(id=self.kwargs.get("pk"))
        time_correction = form.save(commit=True)
        upload.time_correction = time_correction
        upload.save()
        logging.info(f"Successfully created and set time correction for upload {upload.id}")

        return super(TimeCorrectionCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("images:apply_time_correction", args=(self.kwargs.get("pk"),))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["images"] = get_preview_images(self.kwargs.get("pk"))

        return context


class PreviewTimeCorrectionsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = True

        image_ids = json.loads(request.POST.get("images"))

        # Use test image objects instead of querying
        test = request.POST.get("test")

        # Get form entries
        years = int(request.POST.get("years"))
        months = int(request.POST.get("months"))
        days = int(request.POST.get("days"))
        hours = int(request.POST.get("hours"))
        minutes = int(request.POST.get("minutes"))

        start_date = request.POST.get("startDate")
        end_date = request.POST.get("endDate")

        daylight_savings = request.POST.get("daylightSavings")
        daylight_savings_datetime = None

        date_format = "%Y-%m-%dT%H:%M"
        kwargs = {}

        blank_strings = ["", "None"]

        # Reverse effects if already applied
        try:
            correction_applied = Image.objects.get(id=image_ids[0]).upload.time_correction.applied_at is not None
        except Exception:
            correction_applied = False

        # Convert strings to datetime objects
        if start_date and start_date not in blank_strings:
            start_date = datetime.strptime(start_date, date_format)

            # Shift the date for unapplying
            if correction_applied:
                start_date = start_date + relativedelta(
                    years=years, months=months, days=days, hours=hours, minutes=minutes
                )
            kwargs["trigger_timestamp__gte"] = start_date

        if end_date and end_date not in blank_strings:
            end_date = datetime.strptime(end_date, date_format)

            if correction_applied:
                end_date = end_date + relativedelta(years=years, months=months, days=days, hours=hours, minutes=minutes)

            kwargs["trigger_timestamp__lt"] = end_date

        if daylight_savings and daylight_savings not in blank_strings:
            # Calculate the 1st/2nd Sunday of the month
            daylight_savings_month, year = daylight_savings.split("-")

            if daylight_savings_month == "03" or daylight_savings_month == "3" or daylight_savings_month == "11":
                daylight_savings_datetime = get_daylight_savings_date(daylight_savings_month, year)
            else:
                logging.error("Invalid daylight saving months selected in time correction form.")

        new_timestamps = []

        # Add year/day to test stamps
        test_stamps = [datetime(datetime.now().year, 3, day) for day in [1, 4, 7, 10, 13, 16, 19, 22, 25, 28]] + [
            datetime(datetime.now().year, 11, day) for day in [1, 4, 7, 10, 13, 16, 19, 22, 25, 28]
        ]

        # Add hour and minute to test stamps
        test_stamps = [ts + timedelta(hours=index, minutes=index * 7) for index, ts in enumerate(test_stamps)]

        for i, image_id in enumerate(image_ids):
            preview_info = {
                "id": f"{i}00" if test else image_id,
                "color": "",
            }

            timestamp = test_stamps[i] if test else Image.objects.get(id=image_id).trigger_timestamp
            new_timestamp = timestamp

            # Only shift time if it's in the timerange specified
            if test:
                time_range_valid = (
                    kwargs.get("trigger_timestamp__gte") is None or kwargs["trigger_timestamp__gte"] <= timestamp
                ) and (kwargs.get("trigger_timestamp__gte") is None or kwargs["trigger_timestamp__lt"] > timestamp)
            else:
                time_range_valid = Image.objects.filter(id=image_id, **kwargs).exists()

            if time_range_valid and timestamp is not None:
                if correction_applied:
                    new_timestamp = timestamp + relativedelta(
                        years=-years, months=-months, days=-days, hours=-hours, minutes=-minutes
                    )
                else:
                    new_timestamp = timestamp + relativedelta(
                        years=years, months=months, days=days, hours=hours, minutes=minutes
                    )

            # Apply daylight savings shift
            if (
                daylight_savings_datetime
                and new_timestamp is not None
                and new_timestamp.replace(tzinfo=pytz.UTC) >= daylight_savings_datetime.replace(tzinfo=pytz.UTC)
            ):
                if daylight_savings_month == "03" or daylight_savings_month == "3":
                    if correction_applied and timestamp is not None:
                        new_timestamp = timestamp + relativedelta(hours=-1)
                    elif not correction_applied and timestamp is not None:
                        new_timestamp = timestamp + relativedelta(hours=1)
                elif daylight_savings_month == "11":
                    if correction_applied and timestamp is not None:
                        new_timestamp = timestamp + relativedelta(hours=1)
                    elif not correction_applied and timestamp is not None:
                        new_timestamp = timestamp + relativedelta(hours=-1)

            preview_info["newTimestamp"] = new_timestamp

            # Only compare timestamps if both are not None
            if new_timestamp is not None and timestamp is not None:
                if new_timestamp > timestamp:
                    preview_info["color"] = "green"
                elif new_timestamp < timestamp:
                    preview_info["color"] = "red"
            elif new_timestamp is not None and timestamp is None:
                # If we have a new timestamp but no original, mark as green (improvement)
                preview_info["color"] = "green"
            elif new_timestamp is None and timestamp is not None:
                # If we lost the timestamp, mark as red (worse)
                preview_info["color"] = "red"
            # If both are None, leave color as empty string

            new_timestamps.append(preview_info)

        return JsonResponse({"success": success, "previewInfo": new_timestamps})


class ApplyTimeCorrectionView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "images/upload/apply_time_correction.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        upload_id = self.kwargs["pk"]
        context["upload"] = Upload.objects.get(id=upload_id)

        context["images"] = get_preview_images(self.kwargs.get("pk"))

        context["images_applied"] = Image.objects.filter(upload__id=upload_id, time_correction_applied=True).count()
        context["images_not_applied"] = Image.objects.filter(
            upload__id=upload_id, time_correction_applied=False
        ).count()

        return context


class TimeCorrectionStatusView(LoginRequiredMixin, View):
    login_url = settings.LOGIN_URL

    def post(self, request, *args, **kwargs):
        upload_id = request.POST.get("uploadId")

        success = True

        try:
            images_applied = Image.objects.filter(upload__id=upload_id, time_correction_applied=True).count()
            images_not_applied = Image.objects.filter(upload__id=upload_id, time_correction_applied=False).count()
        except Exception:
            success = False

        return JsonResponse({"success": success, "applied": images_applied, "notApplied": images_not_applied})


class FixUploadSetsView(StaffuserRequiredMixin, ListView):
    # View to see all upload sets, and select fixes.
    model = Upload
    login_url = settings.LOGIN_URL
    template_name = "images/upload/fix.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        if self.request.user.is_staff or self.request.user.is_superuser:
            # Replace the blank strings in time error details
            context["uploads"] = Upload.objects.filter(
                ~Q(time_correction=None)
                | ~Q(time_fix_details=None)
                | ~Q(time_error_details=None) & Q(time_error_details__isnull=False) & ~Q(time_error_details__exact="")
            )
            context["num_uploads"] = context["uploads"].count()

            context["recent_uploads"] = Upload.objects.all().order_by("-created")[:50]

        return context


class ModifyUploadSetImagesView(StaffuserRequiredMixin, View):
    # Applies time error fixes according to specified selections.
    def post(self, request, *args, **kwargs):
        success = True

        upload_id = request.POST.get("uploadId")
        upload_obj = Upload.objects.get(id=upload_id)
        time_correction = upload_obj.time_correction

        if upload_obj.time_correction.applied_at is None:
            # Only shift images that are yet to be checked
            images = Image.objects.filter(upload__id=upload_id, time_correction_applied=False)
            logging.info(
                f"Time correction not applied or partially applied to upload {upload_obj.id}. Applying to remaining {images.count()} images..."
            )

            # Handle blank timestamp images
            images.filter(trigger_timestamp=None).update(time_correction_applied=True)
            images = images.filter(~Q(trigger_timestamp=None))

            for image in images.iterator(chunk_size=500):
                try:
                    if (
                        (not time_correction.start_date and not time_correction.end_date)
                        or (
                            time_correction.start_date
                            and time_correction.end_date
                            and time_correction.start_date <= image.trigger_timestamp < time_correction.end_date
                        )
                        or (
                            time_correction.start_date
                            and not time_correction.end_date
                            and time_correction.start_date <= image.trigger_timestamp
                        )
                        or (
                            time_correction.end_date
                            and not time_correction.start_date
                            and time_correction.end_date > image.trigger_timestamp
                        )
                    ):
                        image.trigger_timestamp = image.trigger_timestamp + relativedelta(
                            years=time_correction.years,
                            months=time_correction.months,
                            days=time_correction.days,
                            hours=time_correction.hours,
                            minutes=time_correction.minutes,
                        )
                    if time_correction.daylight_savings:
                        month = time_correction.daylight_savings.month

                        if month == 3:
                            image.trigger_timestamp = image.trigger_timestamp + relativedelta(hours=1)
                        elif month == 11:
                            image.trigger_timestamp = image.trigger_timestamp + relativedelta(hours=-1)

                    image.time_correction_applied = True
                    image.save()
                except BaseException as e:
                    logging.error(f"Error applying time correction to image {image.id}: {e}")

            if not upload_obj.images.filter(time_correction_applied=False).exists():
                time_correction.applied_at = datetime.now()
                time_correction.save()
                logging.info(f"Successfully applied time correction to all images for upload {upload_obj.id}.")
            else:
                logging.info(f"Errors occurred while applying time correction to upload {upload_obj.id}.")

        # Unapply time correction if already applied
        else:
            # Only unapply from images with the correction
            images = Image.objects.filter(upload__id=upload_id, time_correction_applied=True)
            logging.info(
                f"Time correction has already been applied to upload {upload_obj.id}. Unapplying from {images.count()} images..."
            )

            # Handle blank timestamp images
            images.filter(trigger_timestamp=None).update(time_correction_applied=False)
            images = images.filter(~Q(trigger_timestamp=None))

            # Shift dates for unapplying
            if time_correction.start_date:
                start_date = time_correction.start_date + relativedelta(
                    years=time_correction.years,
                    months=time_correction.months,
                    days=time_correction.days,
                    hours=time_correction.hours,
                    minutes=time_correction.minutes,
                )
            else:
                start_date = None

            if time_correction.end_date:
                end_date = time_correction.end_date + relativedelta(
                    years=time_correction.years,
                    months=time_correction.months,
                    days=time_correction.days,
                    hours=time_correction.hours,
                    minutes=time_correction.minutes,
                )
            else:
                end_date = None

            for image in images.iterator(chunk_size=500):
                try:
                    if (
                        (not start_date and not end_date)
                        or (start_date and end_date and start_date <= image.trigger_timestamp < end_date)
                        or (start_date and not end_date and start_date <= image.trigger_timestamp)
                        or (end_date and not start_date and end_date > image.trigger_timestamp)
                    ):
                        image.trigger_timestamp = image.trigger_timestamp + relativedelta(
                            years=-time_correction.years,
                            months=-time_correction.months,
                            days=-time_correction.days,
                            hours=-time_correction.hours,
                            minutes=-time_correction.minutes,
                        )
                    if time_correction.daylight_savings:
                        month = time_correction.daylight_savings.month

                        if month == 3:
                            image.trigger_timestamp = image.trigger_timestamp + relativedelta(hours=-1)
                        elif month == 11:
                            image.trigger_timestamp = image.trigger_timestamp + relativedelta(hours=1)

                    image.time_correction_applied = False
                    image.save()
                except BaseException as e:
                    logging.error(f"Error unapplying time correction from image {image.id}: {e}")

            if not upload_obj.images.filter(time_correction_applied=True).exists():
                time_correction.applied_at = None
                time_correction.save()
                logging.info(f"Successfully unapplied time correction from all images for upload {upload_obj.id}.")
            else:
                logging.info(f"Errors occurred while unapplying time correction to upload {upload_obj.id}.")

        return JsonResponse({"success": success})


# # TODO: This view is currently implemented purely to "test" the annotation functionality
# # This should be moved into the explore app with arbitrary contraints to export annotations
# class UploadExportView(LoginRequiredMixin, StaffuserRequiredMixin, DetailView):
#     model = Upload
#     login_url = settings.LOGIN_URL
#     template_name = "images/upload/export.html"

#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         # Get all images
#         annotated_images = []
#         for image in self.get_object().image_set.all():
#             uncertain_boxes = BoundingBox.objects.uncertain().filter(image=image)
#             valid_or_uncertain_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=image)
#             species_uncertain = [
#                 "uncertain" for bbox in valid_or_uncertain_boxes if not bbox.species_set.valid().exists()
#             ]
#             species_annotated_boxes = Counter(
#                 [
#                     bbox.species_set.valid().first().name.name
#                     for bbox in valid_or_uncertain_boxes
#                     if bbox.species_set.valid().exists()
#                 ]
#             )
#             species_annotated_boxes_str = "<br/>".join(
#                 [f"{name} - {count}" for name, count in species_annotated_boxes.items()]
#             )
#             annotated_images.append(
#                 {
#                     "image": image,
#                     "status": "uncertain" if uncertain_boxes.count() > 0 or len(species_uncertain) > 0 else "certain",
#                     "num_objects": valid_or_uncertain_boxes.count(),
#                     "uncertain_boxes": uncertain_boxes,
#                     "valid_or_uncertain_boxes": valid_or_uncertain_boxes,
#                     "species_annotated_boxes": dict(species_annotated_boxes),
#                     "species_annotated_boxes_str": species_annotated_boxes_str,
#                 }
#             )
#         context["annotated_images"] = annotated_images

#         return context
