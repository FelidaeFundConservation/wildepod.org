from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import FormView, TemplateView

from .models import BlankTagByHuman, Image, SpeciesTag, SpeciesTagByHuman


class TagBlankView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    template_name = "tags/blank.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # TODO: Layer smarter selection logic in here
        # For now, this simple selects an object that does not have any human tag
        context["image"] = Image.objects.filter(blanktagbyhuman__isnull=True).first()

        return context

    def post(self, request, *args, **kwargs):
        # Process the post payload if sent
        if "image_id" in request.POST:
            image_id = request.POST["image_id"]
            object_of_interest = request.POST["object_of_interest"]
            blank = True if object_of_interest == "no" else False
            print(request.POST)
            print(image_id)
            print(object_of_interest)
            print(blank)

            # Create an annotation for this user and image
            obj, created = BlankTagByHuman.objects.get_or_create(
                human=self.request.user, image=Image.objects.get(gdrive_id=image_id), blank=blank
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
                image=Image.objects.get(gdrive_id=image_id),
                species=SpeciesTag.objects.get(name=species),
            )
        return super().get(request)
