import json
from django.conf import settings
from django.http import HttpResponseServerError
from django.views.generic.base import TemplateView

from images.models.image import Image
from images.models.raw_sql import get_prioritized_images, get_uncertain_images, get_images_to_ignore


class WorkflowStateView(TemplateView):
    """
    A view to show the workflow state of the images.
    It has the Ajax calls to build the tables of each step in the workflow.
    """
    template_name = "explore/workflow_state.html"


    def _get_datastore(self):
        try:
            client = settings.DATASTORE_CLIENT
            client.namespace='workflow'

            totals = settings.DATASTORE_CLIENT.get(client.key('total', 'workflow'))

            blank_annotation = settings.DATASTORE_CLIENT.get(client.key('blank_annotation', 'workflow'))
            blank_annotation = {k: v for k, v in blank_annotation.items()}
            blank_annotation['data'] = json.loads(blank_annotation['data'])
            totals['blank_annotation'] = sum(sublist[-1] for sublist in blank_annotation['data'])

            uncertain_images = settings.DATASTORE_CLIENT.get(client.key('uncertain_images', 'workflow'))
            uncertain_images = {k: v for k, v in uncertain_images.items()}
            uncertain_images['data'] = json.loads(uncertain_images['data'])
            totals['uncertain_images'] = sum(sublist[-1] for sublist in uncertain_images['data'])

            species_annotation = settings.DATASTORE_CLIENT.get(client.key('species_annotation', 'workflow'))
            species_annotation = {k: v for k, v in species_annotation.items()}
            species_annotation['data'] = json.loads(species_annotation['data'])
            totals['species_annotation'] = sum(sublist[-1] for sublist in species_annotation['data'])

            return {'totals': totals,
                    'uncertain_images': uncertain_images,
                    'blank_annotation': blank_annotation,
                    'species_annotation': species_annotation}

        except Exception as e:
            print(e)
            return HttpResponseServerError("Error in getting data from datastore")


    def get_context_data(self, **kwargs):
            datastore = self._get_datastore()
            context = super().get_context_data(**kwargs)

            context["total_images"] = datastore['totals']['uploaded_images']
            context["total_images_processed"] = datastore['totals']['processed_images']
            context["total_images_not_processed"] = datastore['totals']['not_processed_images']
            context["total_blank_annotation"] = datastore['totals']['blank_annotation']
            context["total_uncertain_images"] = datastore['totals']['uncertain_images']
            context["total_species_annotation"] = datastore['totals']['species_annotation']

            context["blank_annotation"] = datastore['blank_annotation']
            context["uncertain_images"] = datastore['uncertain_images']
            context["species_annotation"] = datastore['species_annotation']

            return context