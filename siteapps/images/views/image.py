from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http.response import JsonResponse
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
            annotator, created = Annotator.objects.get_or_create(human=request.user)
            queue = ImageQueue.objects.get(assigned_to=annotator)
            queue.partition = partition
            queue.save()
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success, "newPartition": queue.partition})


class CreatePrecomputedQueueView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        image_ids = request.POST.get("image_ids")

        success = True

        try:
            annotator, created = Annotator.objects.get_or_create(human=request.user)

            ImageQueue.objects.filter(assigned_to=annotator).update(assigned_to=None)

            queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME, assigned_to=annotator)
            queue.images.add(*Image.objects.filter(id__in=image_ids))
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success})
