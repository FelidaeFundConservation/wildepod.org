# Move this later to upload/image app
import dropbox
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import FormView, TemplateView

from .models import BlankTagByHuman, Image, SpeciesTag, SpeciesTagByHuman

# Create a dropbox client
dbx = dropbox.Dropbox(settings.DROPBOX_AUTH_TOKEN)


class TagBlankView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "tags/blank.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # TODO: Layer smarter selection logic in here
        # For now, this simple selects an object that does not have any human tag
        image_obj = Image.objects.filter(blanktagbyhuman__isnull=True).first()
        if image_obj:
            response = dbx.sharing_create_shared_link(image_obj.dropbox_file_path)
            image_obj.dropbox_share_url = response.url.replace("?dl=0", "?raw=1")
        context["image"] = image_obj
        # Enables a share link for each dropbox image if share url is missing

        return context

    def post(self, request, *args, **kwargs):
        # Process the post payload if sent
        if "image_id" in request.POST:
            image_id = request.POST["image_id"]
            object_of_interest = request.POST["object_of_interest"]
            blank = True if object_of_interest == "no" else False

            # Create an annotation for this user and image
            obj, created = BlankTagByHuman.objects.get_or_create(
                human=self.request.user, image=Image.objects.get(pk=image_id), blank=blank
            )
        return super().get(request)


class TagSpeciesView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "tags/species.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # TODO: Layer smarter selection logic in here
        # For now, this simple selects an object that already has a human tag

        # TODO: This is currently hacky to build and test the UI.
        # This should be replaced with cleaner way to get non-blank images ranked by the need for a human tag
        no_species_tag = Image.objects.filter(speciestagbyhuman__isnull=True)
        completed_first_pass = no_species_tag.filter(blanktagbyhuman__isnull=False)
        first_non_blank = None
        for img in completed_first_pass:
            for tag in img.blanktagbyhuman_set.all():
                if not tag.blank:
                    first_non_blank = img
                    break
            if first_non_blank:
                break

        if first_non_blank:
            response = dbx.sharing_create_shared_link(first_non_blank.dropbox_file_path)
            first_non_blank.dropbox_share_url = response.url.replace("?dl=0", "?raw=1")

        context["image"] = first_non_blank

        context["species_list"] = SpeciesTag.objects.all()

        return context

    def post(self, request, *args, **kwargs):
        # Process the post payload if sent
        if "image_id" in request.POST:
            image_id = request.POST["image_id"]
            species = request.POST["species"]
            # Create an annotation for this user and image
            obj, created = SpeciesTagByHuman.objects.get_or_create(
                human=self.request.user,
                image=Image.objects.get(pk=image_id),
                species=SpeciesTag.objects.get(name=species),
            )
        return super().get(request)


# TODO: This is a hacky piece of code purely for demo purposes
# This will be refactored later if needed or bits of code will be reused
import base64
import copy
import json
from io import BytesIO

import requests
from django.shortcuts import render
from PIL import Image

from .forms import MLDemoForm
from .tmp_utils import crop_image, load_image_from_binary_string, load_web_image, render_detection_bounding_boxes


class MegaDetectorDemoView(LoginRequiredMixin, TemplateView):
    template_name = "tags/md_demo.html"
    # form_class = MLDemoForm
    success_url = "/tags/md-demo"

    def get(self, request, *args, **kwargs):
        form = MLDemoForm
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = MLDemoForm(request.POST, request.FILES)

        context = {"form": MLDemoForm}

        if form.is_valid():
            url = form.cleaned_data["url"]
            image = form.cleaned_data["image"]

            if not url and not image:
                image_src = "https://storage.googleapis.com/felidae_media_dev/thumbnails/1024x1024/2021-12-10%20-%20henry%20coe%20state%20park%20-%20coe04c/350763565767bd17e8338339786aaf58e0530e3c669e1659105d238394db0605"
                context["image_type"] = "url"
            else:
                image_src = url if url else image
                context["image_type"] = "url" if url else "binary"

            # If url, keep it as-is
            if context["image_type"] == "url":
                context["image"] = image_src
            # Else convert the PIL image to a bytestring
            else:
                img_str = base64.b64encode(image_src.file.getvalue()).decode()
                context["image"] = img_str

            # Run Megadetector on this
            result = requests.post(settings.MEGADETECTOR_URL, json={"image": context["image"]}).json()

            # Rendering output
            # First get a binary version of the image again
            binary_image = (
                load_web_image(context["image"])
                if context["image_type"] == "url"
                else load_image_from_binary_string(context["image"])
            )

            # Crop images.
            images_cropped = crop_image(result["detections"], binary_image)
            context["cropped_images"] = []
            for cropped_img, meta in zip(images_cropped, result["detections"]):
                img_byte_arr = BytesIO()
                cropped_img.save(img_byte_arr, format="jpeg")
                img_byte_arr.seek(0)
                context["cropped_images"].append([base64.b64encode(img_byte_arr.getvalue()).decode(), meta])

            render_detection_bounding_boxes(result["detections"], binary_image)
            img_byte_arr = BytesIO()
            binary_image.save(img_byte_arr, format="jpeg")
            img_byte_arr.seek(0)
            context["output_image"] = base64.b64encode(img_byte_arr.getvalue()).decode()
            context["raw_result"] = json.dumps(result, indent=4)

        return render(request, self.template_name, context)
