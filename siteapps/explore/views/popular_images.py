from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import ListView
from images.models import Image

IMAGE_PAGINATION_LIMIT = 24


class ExplorePopularImagesView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = Image
    template_name = "explore/popular_images.html"

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        # Add in a QuerySet of all the books
        images = Image.objects.filter(social_media_worthy__gt=0).order_by("-social_media_worthy")
        paginator = Paginator(images, IMAGE_PAGINATION_LIMIT)
        page_number = self.request.GET.get("page")
        paged_images = paginator.get_page(page_number)
        context["paged_images"] = paged_images
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        return context


class RemovePopularImage(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        image = get_object_or_404(Image, id=kwargs["pk"])
        image.social_media_worthy = 0
        image.save()

        page = "?page={}".format(request.POST.get('page', '1'))

        # After image removal, send HTTP Redirect to the referer page
        return HttpResponseRedirect("/explore/popular-images/" + page)
