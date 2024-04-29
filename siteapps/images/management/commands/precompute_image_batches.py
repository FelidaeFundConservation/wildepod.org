from django.conf import settings
from django.core.management.base import BaseCommand
from images.models import Annotator, BoundingBox, Category, Image, ImageQueue
from images.views import activity_pipeline_query, species_pipeline_query

NUM_QUEUES = 50

SPECIES_PIPELINE_NAME = "Species"


class Command(BaseCommand):
    help = "Precompute batches of images to assign to annotators, instead of querying entire database each time."

    def handle(self, *args, **options):
        images = Image.objects.all()
        images = species_pipeline_query(images=images, annotator=None)[: settings.ANNOTATION_QUEUE_SIZE * NUM_QUEUES]

        # Remove previously cached queues
        ImageQueue.objects.filter(pipeline_name=SPECIES_PIPELINE_NAME).delete()

        # Create number of queues specified
        for num in range(0, NUM_QUEUES):
            start_index = num * settings.ANNOTATION_QUEUE_SIZE
            end_index = start_index + settings.ANNOTATION_QUEUE_SIZE

            queue_images = images[start_index:end_index]

            queue = ImageQueue.objects.create(pipeline_name=SPECIES_PIPELINE_NAME)
            queue.images.add(*queue_images)
