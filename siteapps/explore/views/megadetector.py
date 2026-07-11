# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# NOTE: THIS IS DEPRECATED

import base64
import json

import requests
from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls.base import reverse_lazy
from django.views.generic import TemplateView
from explore.forms import ExploreMegadetectorForm
from images.models import Bot


class ExploreMegadetectorView(LoginRequiredMixin, StaffuserRequiredMixin, TemplateView):
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
                image_src = "https://scx1.b-cdn.net/csz/news/800a/2021/camera-trap-images-rev-1.jpg"
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
