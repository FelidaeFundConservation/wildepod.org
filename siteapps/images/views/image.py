import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http.response import JsonResponse
from django.utils import timezone
from django.views.generic import DetailView
from django.views.generic.base import TemplateView, View
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    BoundingBox,
    Category,
    Image,
    ImageQueue,
    Species,
    SpeciesName,
    Upload,
)
from images.views import species_pipeline_query
from images.views.annotation import calculate_image_luma

UNANNOTATED_CATEGORY = "unannotated"
SPECIES_PIPELINE_NAME = "Species"


class ImageDetailView(LoginRequiredMixin, DetailView):
    model = Image
    login_url = settings.LOGIN_URL
    template_name = "images/image.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        img_obj = self.get_object()
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        context["social_media_worthy"] = img_obj.social_media_worthy
        context["staff_review_needed"] = img_obj.staff_review_needed

        # TODO: Depending on where this image page is loaded from, the Next, Previous buttons may not be needed.
        try:
            context["next_image"] = Image.objects.filter(
                upload=img_obj.upload, trigger_timestamp__gt=img_obj.trigger_timestamp
            ).first()
        except ObjectDoesNotExist:
            pass
        except BaseException:
            pass
        try:
            context["previous_image"] = Image.objects.filter(
                upload=img_obj.upload, trigger_timestamp__lt=img_obj.trigger_timestamp
            ).last()
        except ObjectDoesNotExist:
            pass
        except BaseException:
            pass

        context["pipeline"] = "species"
        context["species_list"] = SpeciesName.objects.filter(~Q(name=UNANNOTATED_CATEGORY))
        context["birds_list"] = SpeciesName.objects.filter(is_bird=True)
        context["activity_list"] = ActivityType.objects.all()
        context["bounding_boxes"] = BoundingBox.objects.filter(image=img_obj)

        class BboxAnnotationInfo:
            def __init__(self, id, categories, species, activities):
                self.id = id
                self.categories = categories
                self.species = species
                self.activities = activities

        # Gather all annotations for bounding boxes.
        try:
            bboxes = BoundingBox.objects.filter(image=img_obj)
        except (ObjectDoesNotExist, IndexError):
            bboxes = []

        infoList = []

        for bbox in bboxes:
            categories = Category.objects.filter(bounding_box=bbox)
            species = Species.objects.filter(bounding_box=bbox)
            activities = Activity.objects.filter(bounding_box=bbox)

            infoList.append(BboxAnnotationInfo(bbox.id, categories, species, activities))

        context["bbox_all_annotations"] = infoList

        context["luma_adjustment"] = calculate_image_luma(img_obj, context["bounding_boxes"])

        return context


class SetImageQueuePartitionView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        partition = request.POST.get("partition")

        success = True

        try:
            annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)
            queue = ImageQueue.objects.get(assigned_to=annotator)
            queue.partition = partition
            queue.save()
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success, "newPartition": queue.partition})


class CreatePrecomputedQueueView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):

        image_ids = request.POST.getlist("image_ids[]")

        success = True

        try:
            annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)

            ImageQueue.objects.filter(assigned_to=annotator).update(assigned_to=None)

            queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME, assigned_to=annotator)
            queue.images.add(*Image.objects.filter(id__in=image_ids))
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success})


class PrecomputeImageQueuesView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        num_queues = 100

        logging.info(f"Running daily task to precompute {num_queues} image queues...")
        old_queues = ImageQueue.objects.filter(created__lt=timezone.now() - timedelta(hours=12))

        if ImageQueue.objects.all().count() == 0 or old_queues.exists():
            old_queues.delete()
            # Create a proxy queue so the datetime check doesn't pass again while this operation is running
            ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)

            images = Image.objects.all().exclude(species_ai_detections__in=["[]", "['Unknown']"])
            images = species_pipeline_query(images=images, annotator=None)[
                : settings.ANNOTATION_QUEUE_SIZE * num_queues
            ]

            # Remove previously cached queues
            ImageQueue.objects.filter(pipeline_name=SPECIES_PIPELINE_NAME).delete()

            # Create number of queues specified
            for num in range(0, num_queues):
                start_index = num * settings.ANNOTATION_QUEUE_SIZE
                end_index = start_index + settings.ANNOTATION_QUEUE_SIZE

                queue_images = images[start_index:end_index]

                last_image = queue_images[len(queue_images) - 1]

                # Include burst images of last image in queue
                queue_images |= species_pipeline_query(
                    Image.objects.filter(
                        upload=last_image.upload,
                        trigger_timestamp__gte=last_image.trigger_timestamp,
                        trigger_timestamp__lt=last_image.trigger_timestamp + timedelta(seconds=120),
                    ),
                    annotator=None,
                )

                queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)
                queue.images.add(*queue_images)

                logging.info(f"Precomputed queue {num + 1} with {len(queue_images)} images.")

            message = f"Successfully precomputed queues."
            return JsonResponse({"success": True, "message": message})
        else:
            message = f"Precompute process for the day already completed or in progress. There are {ImageQueue.objects.all().count()} queues available."

            logging.info(message)
            return JsonResponse({"success": True, "message": message})
