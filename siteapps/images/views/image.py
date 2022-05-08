from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.views.generic import DetailView
from images.models import BoundingBox, Image


class ImageDetailView(LoginRequiredMixin, DetailView):
    model = Image
    login_url = settings.LOGIN_URL
    template_name = "images/image.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        img_obj = self.get_object()
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        try:
            context["next_image"] = Image.objects.filter(upload=img_obj.upload, trigger_timestamp__gt=img_obj.trigger_timestamp).first()
        except ObjectDoesNotExist:
            pass
        try:
            context["previous_image"] = Image.objects.filter(upload=img_obj.upload, trigger_timestamp__lt=img_obj.trigger_timestamp).last()
        except ObjectDoesNotExist:
            pass
        # Get valid annotations for this image
        bounding_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=img_obj)
        context["bounding_boxes"] = bounding_boxes

        return context
