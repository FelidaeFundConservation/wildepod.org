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
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        try:
            context["next_image"] = self.get_object().get_previous_by_created()
        except ObjectDoesNotExist:
            pass
        try:
            context["previous_image"] = self.get_object().get_next_by_created()
        except ObjectDoesNotExist:
            pass
        # Get valid annotations for this image
        bounding_boxes = BoundingBox.objects.valid_or_uncertain().filter(image=self.get_object())
        context["bounding_boxes"] = bounding_boxes

        return context
