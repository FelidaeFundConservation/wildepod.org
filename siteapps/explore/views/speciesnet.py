import base64
import json
import mimetypes
import os

import google.auth.transport.requests
import google.oauth2.id_token
import requests
from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls.base import reverse_lazy
from django.views.generic import TemplateView
from explore.forms import ExploreSpeciesNetForm
from images.models import Bot
from images.utils.speciesnet_taxonomy import extract_taxonomy_from_string
from images.utils.species_mapper import get_species_mapper


def extract_common_name(taxonomy_string):
    """Extract common name from taxonomy string.

    Example: 'febff896...;mammalia;artiodactyla;...;mule deer' -> 'mule deer'

    Args:
        taxonomy_string: Semicolon-separated taxonomy string

    Returns:
        Common name (last part of taxonomy) or 'unknown' if not found
    """
    if not taxonomy_string:
        return "unknown"
    parts = taxonomy_string.split(';')
    return parts[-1].strip() if parts else "unknown"


class ExploreSpeciesNetView(LoginRequiredMixin, StaffuserRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "explore/speciesnet.html"
    success_url = reverse_lazy("explore:map")

    def get(self, request, *args, **kwargs):
        form = ExploreSpeciesNetForm
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = ExploreSpeciesNetForm(request.POST, request.FILES)

        context = {"form": ExploreSpeciesNetForm}

        if form.is_valid():
            image = form.cleaned_data["image"]

            # Fetch SpeciesNet bot
            bot = Bot.objects.get(name="SpeciesNet", version="v4.0.2a")

            # Get authentication token
            if settings.RUNNING_ON_APP_ENGINE:
                auth_req = google.auth.transport.requests.Request()
                id_token = google.oauth2.id_token.fetch_id_token(auth_req, bot.model_api_url)
            else:
                # Use this command to get the id_token in shell: export ID_TOKEN="$(gcloud auth print-identity-token -q)"
                id_token = os.environ.get("ID_TOKEN")

            # Detect MIME type from file extension
            mime_type, _ = mimetypes.guess_type(image.name)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"  # Default fallback

            # Call SpeciesNet API with multipart form-data
            image.file.seek(0)
            files = {"file": (image.name, image.file, mime_type)}
            response = requests.post(
                bot.model_api_url,
                files=files,
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=300,
            )

            result = response.json()

            # Get top prediction for bounding box labels
            top_prediction = result.get("prediction", "")
            species_name = extract_common_name(top_prediction)

            # Build bounding boxes with species label
            bboxes = [
                {
                    "id": f"{i}",
                    "category": species_name,  # Show species instead of detection category
                    "confidence": detection["conf"],
                    "x": detection["bbox"][0],
                    "y": detection["bbox"][1],
                    "w": detection["bbox"][2],
                    "h": detection["bbox"][3],
                }
                for i, detection in enumerate(result.get("detections", []))
            ]

            # Build top 5 classifications list with WildePod species mapping
            classifications = result.get("classifications", {})
            classes = classifications.get("classes", [])
            scores = classifications.get("scores", [])

            species_mapper = get_species_mapper()
            top_classifications = []

            for cls, score in zip(classes[:5], scores[:5]):
                # Extract UUID and common name from taxonomy string
                speciesnet_uuid, common_name = extract_taxonomy_from_string(cls)

                # Try to find matching WildePod species
                wildepod_species = None
                if speciesnet_uuid:
                    wildepod_species = species_mapper.lookup_species(speciesnet_uuid)

                classification = {
                    "species": common_name,
                    "full_taxonomy": cls,
                    "score": score,
                    "wildepod_species": wildepod_species,  # SpeciesName object or None
                    "speciesnet_uuid": str(speciesnet_uuid) if speciesnet_uuid else None,
                }
                top_classifications.append(classification)

            # Pass data to template
            image.file.seek(0)
            img_str = base64.b64encode(image.file.read()).decode()
            context["image"] = img_str
            context["image_type"] = "binary"
            context["raw_result"] = json.dumps(result, indent=4)
            context["bboxes"] = bboxes
            context["top_classifications"] = top_classifications

            return render(request, self.template_name, context)
