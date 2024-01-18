from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.views.generic import DetailView
from images.models import Activity, ActivityType, BoundingBox, Category, Image, Species, SpeciesName, Upload
from images.views.annotation import calculate_image_luma

UNANNOTATED_CATEGORY = "unannotated"


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
        try:
            context["previous_image"] = Image.objects.filter(
                upload=img_obj.upload, trigger_timestamp__lt=img_obj.trigger_timestamp
            ).last()
        except ObjectDoesNotExist:
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
