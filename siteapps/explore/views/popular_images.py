import json

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.http.response import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import ListView

from siteapps.images.models import Image, SpeciesName

IMAGE_PAGINATION_LIMIT = 24


class ExplorePopularImagesView(LoginRequiredMixin, ListView):
    login_url = settings.LOGIN_URL
    model = Image
    template_name = "explore/popular_images.html"

    def get_context_data(self, **kwargs):
        # Call the base implementation first to get a context
        context = super().get_context_data(**kwargs)
        
        # Get species filter from query params - filter out empty strings
        species_ids = [s for s in self.request.GET.getlist('species') if s]
        
        # Get per_page parameter
        per_page = self.request.GET.get('per_page', '24')
        try:
            if per_page.lower() == 'all':
                per_page_int = None
            else:
                per_page_int = int(per_page)
                # Limit to reasonable values
                if per_page_int not in [12, 24, 48, 96]:
                    per_page_int = 24
        except (ValueError, TypeError):
            per_page_int = 24
        
        # Base queryset
        images = (
            Image.objects.filter(social_media_worthy__gt=0)
            .exclude(species_checked_by=None)
        )
        
        # Apply species filter if provided
        if species_ids:
            # Filter images that have at least one of the selected species
            images = images.filter(
                boundingbox__species__name_id__in=species_ids
            ).distinct()
        
        images = images.order_by("-trigger_timestamp", "-id", "-social_media_worthy")
        
        # Paginate with custom per_page or show all
        if per_page_int is None:
            # Show all images
            paged_images = images
            context["paged_images"] = paged_images
            context["is_paginated"] = False
        else:
            paginator = Paginator(images, per_page_int)
            page_number = self.request.GET.get("page")
            paged_images = paginator.get_page(page_number)
            context["paged_images"] = paged_images
            context["is_paginated"] = True
            
            # Generate elided page range
            context["page_range"] = self.get_elided_page_range(paged_images)
        
        context["dropbox_prefix"] = settings.DROPBOX_URL_PREFIX
        context["per_page"] = per_page
        
        # Get all active species for the filter dropdown
        context["all_species"] = SpeciesName.objects.filter(active=True).order_by('name')
        context["selected_species"] = [int(s) for s in species_ids] if species_ids else []
        
        return context
    
    def get_elided_page_range(self, page_obj):
        """
        Generate an elided page range showing first pages, current page context, 
        last pages, and ellipses in between.
        Example: [1, 2, 3, '...', 45, 46, 47, '...', 98, 99, 100]
        """
        current_page = page_obj.number
        num_pages = page_obj.paginator.num_pages
        
        # For small page counts, show all pages
        if num_pages <= 10:
            return range(1, num_pages + 1)
        
        # Always show first 2 and last 2 pages
        # Show 2 pages on each side of current page
        pages = []
        
        # First pages (always show pages 1-2)
        for i in range(1, min(3, num_pages + 1)):
            pages.append(i)
        
        # Pages around current page
        start = max(3, current_page - 2)
        end = min(num_pages - 2, current_page + 2)
        
        # Add ellipsis before current range if needed
        if start > 3:
            pages.append('...')
        
        # Add current page range
        for i in range(start, end + 1):
            if i not in pages and i < num_pages - 1:
                pages.append(i)
        
        # Add ellipsis after current range if needed
        if end < num_pages - 2:
            pages.append('...')
        
        # Last pages (always show last 2 pages)
        for i in range(max(num_pages - 1, 3), num_pages + 1):
            if i not in pages:
                pages.append(i)
        
        return pages


class RemovePopularImageView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        success = True

        image_ids = request.POST.get("imageIds")

        if image_ids:
            image_ids = json.loads(image_ids)

            for image_id in image_ids:
                try:
                    image = Image.objects.get(id=image_id)
                    image.social_media_worthy = 0
                    image.save()
                except Exception:
                    success = False

        return JsonResponse({"success": success})
