# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
from datetime import datetime, timedelta

from braces.views import StaffuserRequiredMixin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q
from django.http.response import JsonResponse
from django.utils import timezone
from django.views.generic import DetailView
from django.views.generic.base import TemplateView, View
from images.models import (
    Activity,
    ActivityType,
    Annotator,
    BoundingBox,
    Category,
    Image,
    ImageQueue,
    Species,
    SpeciesName,
    StaffReviewFlagReason,
    Upload,
)
from images.views import species_pipeline_query
from images.views.annotation import calculate_image_luma, set_widget_data

UNANNOTATED_CATEGORY = "unannotated"
UNKNOWN_CATEGORY = "unknown"
SPECIES_PIPELINE_NAME = "Species"


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
        # Without these the Reason select renders empty, and since a flag without a reason is
        # rejected, the Flag for Staff Review checkbox on this page cannot be used at all.
        context["staff_review_flag_reasons"] = StaffReviewFlagReason.choices

        # Which sequence Previous/Next walk. Reaching this page from a search result is the
        # obvious click -- the thumbnail is a link, the queue is a smaller button under it --
        # and stepping through the upload's neighbours there is answering a question nobody
        # asked. So when this image is part of the queue the annotator is working, walk that
        # instead, and say which sequence it is either way.
        context.update(self._queue_navigation(img_obj) or self._upload_navigation(img_obj))

        context["pipeline"] = "species"
        context["species_list"] = SpeciesName.objects.filter(~Q(name=UNKNOWN_CATEGORY), active=True)
        context["birds_list"] = SpeciesName.objects.filter(is_bird=True)
        context["activity_list"] = ActivityType.objects.all()
        context["bounding_boxes"] = BoundingBox.objects.filter(image=img_obj)

        set_widget_data(context, img_obj, context["species_list"])

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

    def _queue_navigation(self, image):
        """Previous/Next through the annotator's own queue, if this image is in it.

        Returns None when it is not, so the caller falls back to the upload. Nothing here
        creates, claims or advances a queue -- opening an image to look at it must not disturb
        a batch someone is part way through.
        """
        annotator = Annotator.objects.filter(type="human", human=self.request.user).first()

        if not annotator:
            return None

        queue = ImageQueue.objects.filter(assigned_to=annotator).exclude(image_order=[]).first()

        if not queue or str(image.id) not in queue.image_order:
            return None

        order = queue.image_order
        index = order.index(str(image.id))

        # Nearest surviving neighbour rather than simply index +/- 1: image_order holds ids,
        # and one being deleted must not sever the queue at that point.
        by_id = {str(sibling.id): sibling for sibling in Image.objects.filter(id__in=order)}
        after = [by_id[i] for i in order[index + 1 :] if i in by_id]
        before = [by_id[i] for i in order[:index] if i in by_id]

        return {
            "nav_scope": "queue",
            # Plain hrefs, not the queue cursor the annotate page moves: opening an image to
            # look at it must not advance a batch someone is part way through.
            "nav_mode": "links",
            "next_image": after[0] if after else None,
            "previous_image": before[-1] if before else None,
            "nav_position": index + 1,
            "nav_total": len(order),
        }

    def _upload_navigation(self, image):
        """Previous/Next through the images either side of this one in its upload."""
        timestamp = image.trigger_timestamp

        if timestamp is None:
            # Nothing to order by, and the comparisons below would raise. Previously this
            # blew up into a bare `except BaseException: pass`, which disabled both buttons
            # without ever saying why.
            return {"nav_scope": "upload", "nav_mode": "links", "next_image": None, "previous_image": None}

        siblings = Image.objects.filter(upload=image.upload)

        # Tie-broken on `created` to match Image.Meta.ordering. A strict comparison on the
        # timestamp alone skips every image sharing it, so a burst -- which is exactly what a
        # camera trap produces, several frames stamped the same second -- was unreachable.
        later = Q(trigger_timestamp__gt=timestamp) | Q(trigger_timestamp=timestamp, created__lt=image.created)
        earlier = Q(trigger_timestamp__lt=timestamp) | Q(trigger_timestamp=timestamp, created__gt=image.created)

        return {
            "nav_scope": "upload",
            "nav_mode": "links",
            "next_image": siblings.filter(later).first(),
            "previous_image": siblings.filter(earlier).last(),
            "nav_position": siblings.filter(earlier).count() + 1,
            "nav_total": siblings.count(),
        }


class SetImageQueuePartitionView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        partition = request.POST.get("partition")

        success = True

        try:
            annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)
            queue = ImageQueue.objects.get(assigned_to=annotator)
            queue.partition = partition
            queue.save()
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success, "newPartition": queue.partition})


class MoveSearchedQueueCursorView(LoginRequiredMixin, View):
    """Moves a searched queue's cursor without recording anything about the image.

    A searched queue is navigated by `position`, not by the `partition` timestamp that
    SetImageQueuePartitionView writes, so that view cannot move it -- clicking a grid
    thumbnail in a searched queue reloaded onto the same image.

    Deliberately not the annotation processor's skip path. Skipping adds the annotator to the
    image's skipped list and can trip the automatic review flag, which is right for a
    volunteer saying "I cannot do this one" and wrong for staff paging through a batch they
    assembled to look at.
    """

    def post(self, request, *args, **kwargs):
        image_id = request.POST.get("image_id")
        # "past" for moving on from the image just looked at, "at" for jumping to one.
        mode = request.POST.get("mode", "past")

        annotator, _ = Annotator.objects.get_or_create(type="human", human=request.user)
        queue = ImageQueue.objects.filter(assigned_to=annotator).exclude(image_order=[]).first()

        if not queue:
            return JsonResponse({"success": False, "error": "No searched queue is assigned to you."})

        moved = queue.advance_past(image_id) if mode == "past" else queue.move_to(image_id)

        if not moved:
            return JsonResponse({"success": False, "error": "That image is not in your queue."})

        return JsonResponse({"success": True, "position": queue.position, "total": len(queue.image_order)})


class CreatePrecomputedQueueView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):

        image_ids = request.POST.getlist("image_ids[]")

        success = True

        try:
            annotator, created = Annotator.objects.get_or_create(type="human", human=request.user)

            ImageQueue.objects.filter(assigned_to=annotator).update(assigned_to=None)

            # image_ids arrives in the order the results table was showing, so it is kept as
            # the queue's order. A many to many has none of its own, and reading it back would
            # otherwise fall through to Image.Meta.ordering and serve the batch by capture
            # date whatever the staff member had sorted or filtered by.
            queue = ImageQueue.objects.create(
                pipeline_name=SPECIES_PIPELINE_NAME,
                assigned_to=annotator,
                image_order=[str(image_id) for image_id in image_ids],
            )
            queue.images.add(*Image.objects.filter(id__in=image_ids))
        except ObjectDoesNotExist:
            success = False

        return JsonResponse({"success": success})


class BulkImageActionView(LoginRequiredMixin, StaffuserRequiredMixin, View):
    """Applies one action to the images a staff member ticked in the search results.

    Everything here acts on an explicit list of image ids, never on the current filter. The
    search page keeps those two apart on purpose: the filter decides what you are looking at,
    the tick boxes decide what you are about to change.
    """

    CLEAR_FLAG = "clear_flag"
    ASSIGN_EXPERT = "assign_expert"

    def handle_no_permission(self, request=None):
        """Override to handle braces compatibility with newer Django versions."""
        # braces' StaffuserRequiredMixin passes request, Django's AccessMixin does not take it.
        # Without this a non-staff user raises TypeError instead of being turned away, which
        # would turn the permission check into a 500. Same shim as SearchImagesView.
        from django.contrib.auth.mixins import AccessMixin

        return AccessMixin.handle_no_permission(self)

    def post(self, request, *args, **kwargs):
        image_ids = request.POST.getlist("image_ids[]")
        action = request.POST.get("action")

        if not image_ids:
            return JsonResponse({"success": False, "error": "No images selected."}, status=400)

        images = Image.objects.filter(id__in=image_ids)

        if action == self.CLEAR_FLAG:
            return self._clear_flag(images)

        if action == self.ASSIGN_EXPERT:
            return self._assign_expert(request, images)

        return JsonResponse({"success": False, "error": f"Unknown action: {action}"}, status=400)

    def _clear_flag(self, images):
        """Takes the selected images back out of the staff review queue."""
        # One UPDATE rather than a save() per image: clearing a hundred rows is the normal
        # case here, and Image keeps no history table, so nothing is lost by not going through
        # clear_staff_review_flag() instance by instance. The values come from the model either
        # way, including the review timestamp -- without it the automatic skip threshold would
        # flag every one of these again as soon as a volunteer skipped it.
        cleared = images.update(**Image.cleared_staff_review_values())

        return JsonResponse({"success": True, "action": self.CLEAR_FLAG, "count": cleared})

    def _assign_expert(self, request, images):
        """Hands the selected images to an expert as annotation work."""
        expert_id = request.POST.get("expert_id")

        try:
            expert = get_user_model().objects.get(id=expert_id, is_expert=True)
        except (get_user_model().DoesNotExist, ValidationError, ValueError):
            # ValidationError/ValueError cover a malformed UUID, which would otherwise 500
            return JsonResponse({"success": False, "error": "Unknown expert."}, status=400)

        annotator, _ = Annotator.objects.get_or_create(type="human", human=expert)

        # Add to the queue the expert already holds rather than replacing it.
        # CreatePrecomputedQueueView clears an annotator's existing assignment before building
        # a new queue; reusing that here would mean two staff assigning work to the same expert
        # in one afternoon silently destroy each other's batch. Appending makes a second
        # assignment read as "here is some more", which is what the assigner meant.
        #
        # Built queues only. Annotating anything assigns the expert an automatically
        # precomputed queue, and add_images() will not record an order on one of those -- so
        # adopting it here dissolved the batch into whatever the system had already handed
        # them: no order, so nothing to serve it by, no count in the nav, and a success
        # response to the staff member either way. An expert who had ever annotated anything
        # swallowed assignments silently.
        queue = ImageQueue.objects.filter(assigned_to=annotator).exclude(image_order=[]).first()

        if queue is None:
            queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME, assigned_to=annotator)

        # add_images() rather than images.add(): if the expert already had a queue from their
        # own search it carries a recorded order, and images added straight to the many to many
        # would never be served to them.
        queue.add_images(images)

        # partition excludes anything before it, and it advances as the expert works. Newly
        # added images older than that mark would be invisible, so appending resets it. The
        # cost is that the expert sees the whole queue from the start again; the pipeline
        # filters drop whatever they have already annotated. Queues with a recorded order use
        # `position` instead, which needs no reset -- appended images land after it.
        queue.partition = datetime.min
        queue.save()

        return JsonResponse(
            {
                "success": True,
                "action": self.ASSIGN_EXPERT,
                "count": images.count(),
                "expert": str(annotator),
            }
        )


class PrecomputeImageQueuesView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        num_queues = 100

        logging.info(f"Running bidaily task to precompute {num_queues} image queues...")
        old_queues = ImageQueue.objects.filter(created__lt=timezone.now() - timedelta(hours=12))

        if ImageQueue.objects.all().count() == 0 or old_queues.exists():
            old_queues.delete()
            # Create a proxy queue so the datetime check doesn't pass again while this operation is running
            ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)

            images = Image.objects.all().exclude(species_ai_detections__in=["[]", "['Unknown']"])
            images = list(
                species_pipeline_query(images=images, annotator=None)[: settings.ANNOTATION_QUEUE_SIZE * num_queues]
            )

            # Remove previously cached queues
            ImageQueue.objects.filter(pipeline_name=SPECIES_PIPELINE_NAME).delete()

            # Create number of queues specified
            for num in range(0, num_queues):
                start_index = num * settings.ANNOTATION_QUEUE_SIZE
                end_index = start_index + settings.ANNOTATION_QUEUE_SIZE

                queue_images = images[start_index:end_index]

                if len(queue_images) > 0:
                    last_image = queue_images[len(queue_images) - 1]

                    # Include burst images of last image in queue
                    if last_image.trigger_timestamp is not None:
                        queue_images += list(
                            species_pipeline_query(
                                Image.objects.filter(
                                    upload=last_image.upload,
                                    trigger_timestamp__gte=last_image.trigger_timestamp,
                                    trigger_timestamp__lt=last_image.trigger_timestamp + timedelta(seconds=120),
                                ),
                                annotator=None,
                            )
                        )

                    queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)
                    queue.images.set(queue_images)

                    logging.info(f"Precomputed queue {num + 1} with {len(queue_images)} images.")

            message = f"Successfully precomputed queues."
            return JsonResponse({"success": True, "message": message})
        else:
            message = f"Precompute process for the period already completed or in progress. There are {ImageQueue.objects.all().count()} queue(s) available."

            logging.info(message)
            return JsonResponse({"success": True, "message": message})
