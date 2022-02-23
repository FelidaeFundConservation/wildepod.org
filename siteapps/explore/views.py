import base64
import json

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls.base import reverse_lazy
from django.views.generic import ListView, TemplateView
from images.models import Bot
from locations.models import CameraStation
import requests

from .forms import ExploreMegadetectorForm


class ExploreHomeView(LoginRequiredMixin, TemplateView):
    template_name = "explore/main.html"


# TODO: Gate this to only staff members
class ExploreMapView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = CameraStation
    template_name = "explore/map.html"


class ExploreMegadetectorView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "explore/megadetector.html"
    success_url = reverse_lazy("explore:map")

    def get(self, request, *args, **kwargs):
        form = ExploreMegadetectorForm
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = ExploreMegadetectorForm(request.POST, request.FILES)

        context = {"form": ExploreMegadetectorForm}

        if form.is_valid():
            url = form.cleaned_data["url"]
            image = form.cleaned_data["image"]

            if not url and not image:
                image_src = "https://storage.googleapis.com/felidae_media_dev/compressed/1024/024e9187cf365dcd147642ab585ddacef0c6a074d1c77f49d4a341da4e950582.jpg"
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

            # TODO: Probably a better way to handle this. Hardcoded for now. Might not even need a model/record for this
            bot, _ = Bot.objects.get_or_create(
                name="MegaDetector",
                version="4.1.0",
                task_type="Object Detection",
                model_api_url=settings.MEGADETECTOR_URL,
                model_file_url=f"gs://{settings.MODEL_STORAGE_BUCKET}/md_v4.1.0.pb",
            )

            # Call the MegaDetector cloud function
            result = requests.post(
                bot.model_api_url,
                json={"image": context["image"], "model": bot.model_file_url},
            ).json()

            # Create a new annotation object
            bboxes = [
                {
                    "id": f"{i}",
                    "category": detection["category"],
                    "confidence": detection["conf"],
                    "x": detection["bbox"][0],
                    "y": detection["bbox"][1],
                    "w": detection["bbox"][2],
                    "h": detection["bbox"][3],
                }
                for i, detection in enumerate(result["detections"])
            ]

            # Collect all annotations and send them to the template in the right format
            context["raw_result"] = json.dumps(result, indent=4)
            context["bboxes"] = bboxes

            return render(request, self.template_name, context)
