import json

from django.conf import settings
from django.http import HttpResponseServerError
from django.shortcuts import render
from django.views.generic.base import TemplateView

from siteapps.images.models.annotation import Activity, Category, Species
from siteapps.images.models.image import Image
from siteapps.images.models.raw_sql import get_images_to_ignore, get_prioritized_images, get_uncertain_images


class WorkflowStateView(TemplateView):
    """
    A view to show the workflow state of the images.
    It has the Ajax calls to build the tables of each step in the workflow.
    """

    template_name = "explore/workflow_state.html"

    def _get_datastore(self):
        try:
            client = settings.DATASTORE_CLIENT
            
            # Check if Datastore is available (not available in local development)
            if client is None:
                return HttpResponseServerError("Datastore is not available in local development")
            
            client.namespace = "workflow"

            totals = settings.DATASTORE_CLIENT.get(client.key("total", "workflow"))

            blank_annotation = settings.DATASTORE_CLIENT.get(client.key("blank_annotation", "workflow"))
            blank_annotation = {k: v for k, v in blank_annotation.items()}
            blank_annotation["data"] = json.loads(blank_annotation["data"])
            totals["blank_annotation"] = sum(sublist[-1] for sublist in blank_annotation["data"])

            uncertain_images = settings.DATASTORE_CLIENT.get(client.key("uncertain_images", "workflow"))
            uncertain_images = {k: v for k, v in uncertain_images.items()}
            uncertain_images["data"] = json.loads(uncertain_images["data"])
            totals["uncertain_images"] = sum(sublist[-1] for sublist in uncertain_images["data"])

            species_annotation = settings.DATASTORE_CLIENT.get(client.key("species_annotation", "workflow"))
            species_annotation = {k: v for k, v in species_annotation.items()}
            species_annotation["data"] = json.loads(species_annotation["data"])
            totals["species_annotation"] = sum(sublist[-1] for sublist in species_annotation["data"])

            animal_activity_annotation = settings.DATASTORE_CLIENT.get(client.key("animal_activity", "workflow"))
            animal_activity_annotation = {k: v for k, v in animal_activity_annotation.items()}
            animal_activity_annotation["data"] = json.loads(animal_activity_annotation["data"])
            totals["animal_activity_annotation"] = sum(sublist[-1] for sublist in animal_activity_annotation["data"])

            human_behavior_annotation = settings.DATASTORE_CLIENT.get(client.key("human_behavior", "workflow"))
            human_behavior_annotation = {k: v for k, v in human_behavior_annotation.items()}
            human_behavior_annotation["data"] = json.loads(human_behavior_annotation["data"])
            totals["human_behavior_annotation"] = sum(sublist[-1] for sublist in human_behavior_annotation["data"])

            return {
                "totals": totals,
                "uncertain_images": uncertain_images,
                "blank_annotation": blank_annotation,
                "species_annotation": species_annotation,
                "animal_activity": animal_activity_annotation,
                "human_behavior": human_behavior_annotation,
            }

        except Exception as e:
            print(e)
            return HttpResponseServerError("Error in getting data from datastore")

    def get(self, request, *args, **kwargs):
        """Override get to check datastore availability before rendering"""
        datastore = self._get_datastore()
        
        # If datastore retrieval failed, show error page
        if isinstance(datastore, HttpResponseServerError):
            error_message = """
            <h2>Workflow State Not Available</h2>
            <p>The workflow state page requires Google Cloud Datastore, which is not available in local development.</p>
            <p>This feature is only available in the deployed GCP environment.</p>
            """
            return render(request, 'explore/error.html', {'error_message': error_message}, status=503)
        
        # Store datastore in request for use in get_context_data
        request.datastore = datastore
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        # Get datastore from request (set in get method)
        datastore = self.request.datastore
        context = super().get_context_data(**kwargs)

        # Key Findings
        context["totals_last_update"] = datastore["totals"]["last_update"]
        context["total_images"] = datastore["totals"]["uploaded_images"]
        context["total_images_processed"] = datastore["totals"]["processed_images"]
        context["total_images_not_processed"] = datastore["totals"]["not_processed_images"]

        # Category - Rename variables properly
        context["total_blank_annotation"] = datastore["totals"]["blank_annotation"]
        context["blank_annotation"] = datastore["blank_annotation"]
        context["total_uncertain_images"] = datastore["totals"]["uncertain_images"]
        context["uncertain_images"] = datastore["uncertain_images"]

        # Species
        context["total_species_annotation"] = datastore["totals"]["species_annotation"]
        context["species_annotation"] = datastore["species_annotation"]

        # Animal Activity
        context["animal_activity"] = datastore["animal_activity"]
        context["total_animal_activity"] = datastore["totals"]["animal_activity_annotation"]

        # Human Behavior
        context["human_behavior"] = datastore["human_behavior"]
        context["total_human_behavior"] = datastore["totals"]["human_behavior_annotation"]

        # Identified/Observed
        context["categories"] = Category.get_categories_group_by()
        context["species"] = Species.get_species_group_by()
        context["animal_activity_observed"] = Activity.get_activities_group_by_category("animal")
        context["human_behavior_observed"] = Activity.get_activities_group_by_category("human")

        # Pipelines
        # Still to count the uncertain for all steps.
        # Not all values are directly from the database/datastore, some are calculated.
        """
            Categories
            Total = Uploaded Images
            First annotation = One annotation (by now, forget validation)
            Annotated = Total - First

            Species
            Total = Categories Annotated - Animal
            First annotation = One annotation (by now, forget validation)
            Annotated = Total - First

            Animal Annotated
            Total = Species Annotated
            First annotation = One annotation (by now, forget validation)
            Annotated = Total - First

            Human Behavior
            Total = Categories Annotated - Human
            First annotation = One annotation (by now, forget validation)
            Annotated = Total - First
            """
        context["pipe_category_input"] = context["total_images"]
        context["pipe_category_first_round"] = context["total_blank_annotation"]
        context["pipe_category_annotated"] = context["pipe_category_input"] - context["pipe_category_first_round"]

        context["pipe_species_input"] = context["total_species_annotation"]
        context["pipe_species_first_round"] = context["pipe_species_input"] - Species.get_total_species()
        context["pipe_species_annotated"] = Species.get_total_species()

        animal_activity_observed = sum([el["total"] for el in context["animal_activity_observed"]])
        context["pipe_animal_activity_input"] = context["total_animal_activity"] + animal_activity_observed
        context["pipe_animal_activity_first_round"] = context["total_animal_activity"]
        context["pipe_animal_activity_annotated"] = animal_activity_observed

        human_behavior_observed = sum([el["total"] for el in context["human_behavior_observed"]])
        context["pipe_human_behavior_input"] = context["total_human_behavior"] + human_behavior_observed
        context["pipe_human_behavior_first_round"] = context["total_human_behavior"]
        context["pipe_human_behavior_annotated"] = human_behavior_observed

        return context
