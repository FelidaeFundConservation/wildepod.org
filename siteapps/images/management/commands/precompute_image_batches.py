import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from images.models import Annotator, BoundingBox, Category, Image, ImageQueue
from images.views import activity_pipeline_query, species_pipeline_query

SPECIES_PIPELINE_NAME = "Species"


class Command(BaseCommand):
    help = "Precompute batches of images to assign to annotators, instead of querying entire database each time."

    def add_arguments(self, parser):
        parser.add_argument("--num_queues", type=int, default=35, help="Number of queues to compute."),

    def handle(self, *args, **options):
        num_queues = options.get("num_queues")

        logging.info(f"Running task to precompute {num_queues} image queues...")

        images = Image.objects.all().exclude(species_ai_detections__in=["[]", "['Unknown']"])
        images = species_pipeline_query(images=images, annotator=None)[: settings.ANNOTATION_QUEUE_SIZE * num_queues]

        # Remove previously cached queues
        ImageQueue.objects.filter(pipeline_name=SPECIES_PIPELINE_NAME).delete()

        # Create number of queues specified
        for num in range(0, num_queues):
            start_index = num * settings.ANNOTATION_QUEUE_SIZE
            end_index = start_index + settings.ANNOTATION_QUEUE_SIZE

            queue_images = images[start_index:end_index]

            last_image = queue_images[len(queue_images) - 1]

            # Include burst images of last image in queue
            queue_images |= species_pipeline_query(
                Image.objects.filter(
                    upload=last_image.upload,
                    trigger_timestamp__gte=last_image.trigger_timestamp,
                    trigger_timestamp__lt=last_image.trigger_timestamp + timedelta(seconds=120),
                ),
                annotator=None,
            )

            queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)
            queue.images.add(*queue_images)

            logging.info(f"Precomputed queue {num + 1} with {len(queue_images)} images.")
