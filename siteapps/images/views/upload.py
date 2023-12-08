import json
import logging
import threading

from braces.views import StaffuserRequiredMixin
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
from images.forms import UploadCompleteForm, UploadForm
from images.models import Annotator, BoundingBox, Image, TimeCorrection, Upload
from images.processors import process_upload
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
        years = self.request.POST.get("time_correction_years") or 0
        months = self.request.POST.get("time_correction_months") or 0
        days = self.request.POST.get("time_correction_days") or 0
        hours = self.request.POST.get("time_correction_hours") or 0
        minutes = self.request.POST.get("time_correction_minutes") or 0

        daylight_savings = self.request.POST.get("daylight_savings_correction") or None

        upload = form.save(commit=False)

        if not (years == months == days == hours == minutes == 0 and daylight_savings is None):
            time_correction, created = TimeCorrection.objects.get_or_create(upload__id=upload.id)

            time_correction.years = years
            time_correction.months = months
            time_correction.days = days
            time_correction.hours = hours
            time_correction.minutes = minutes

            time_correction.daylight_savings = daylight_savings

            time_correction.save()

            upload.time_correction = time_correction
            upload.save()

            logging.info(f"Saved time correction information  for upload {upload.id}.")
        else:
            logging.info(f"No time correction information entered for upload {upload.id}.")

        return super(UploadCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("images:complete_upload", args=(self.object.id,))


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
            context["uploads"] = Upload.objects.filter(~Q(time_correction=None))
            context["num_uploads"] = context["uploads"].count()

            context["first_timestamps"] = [
                upload.images.first().trigger_timestamp if upload.images.first() else None
                for upload in context["uploads"]
            ]

            context["zipped_data"] = zip(context["uploads"], context["first_timestamps"])

        return context


class GetUploadSetImageInfoView(StaffuserRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = None

        set_images = {}
        set_ids = request.POST.get("setIds")
        num_results = request.POST.get("maxResults")

        if num_results:
            max_results = int(num_results)
        else:
            max_results = float("inf")

        for set_id in set_ids.split(","):
            imageList = []

            try:
                totalImages = Upload.objects.get(id=set_id).images.all().count()
                stepValue = max(1, totalImages // max_results)

                for image in Upload.objects.get(id=set_id).images.all()[::stepValue]:
                    imageList.append({"id": image.id, "triggerTime": image.trigger_timestamp, "newTime": None})

                set_images[set_id] = imageList

            except ObjectDoesNotExist:
                success = False

        success = True

        return JsonResponse({"success": success, "setImages": set_images})


class SetUploadSetTimeFixDetailsView(StaffuserRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = None

        set_id = request.POST.get("setId")
        time_fix_details = request.POST.get("timeFixDetails")

        try:
            upload_set = Upload.objects.get(id=set_id)
            upload_set.time_fix_details = time_fix_details
            upload_set.save()
            success = True
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success})


class ModifyUploadSetImagesView(StaffuserRequiredMixin, View):
    # Applies time error fixes according to specified selections.
    def post(self, request, *args, **kwargs):
        images_to_change = request.POST.get("imagesToChange")

        errors = []

        success = True

        for image_id, new_timestamp in json.loads(images_to_change):
            try:
                target_image = Image.objects.get(id=image_id)
                target_image.trigger_timestamp = new_timestamp
                target_image.save()
            except Exception as error:
                errors.append([image_id, error])
                success = False

        return JsonResponse({"success": success, "errors": errors})


class ClearTimeErrorDetailsView(StaffuserRequiredMixin, View):
    # Clear the time error details, which marks it as resolved.
    def post(self, request, *args, **kwargs):
        upload_ids = request.POST.get("uploadIds", "[]")
        upload_ids = json.loads(upload_ids)

        errors = []

        success = True

        for upload_id in upload_ids:
            try:
                upload_set = Upload.objects.get(id=upload_id)
                upload_set.time_error_details = None
                upload_set.save()
            except Exception as error:
                errors.append([upload_id, error])
                success = False

        return JsonResponse({"success": success, "errors": errors})


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
