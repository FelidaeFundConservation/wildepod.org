import pandas as pd


from django.http import JsonResponse
from django.views.generic import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import TemplateView


from images.models.image import Image
from images.models.raw_sql import get_prioritized_images, get_uncertain_images, get_images_to_ignore




def _pd_group_images(images):
    """
    Group the images objects by macrosite and camera station
    using pandas
    """
    df = pd.DataFrame([{'Macrosite': i.macrosite,\
                        'Priority': i.priority, \
                        'Trigger': i.ts,} for i in images])

    try:
        result = df.groupby(['Macrosite', 'Priority'])['Trigger'].agg(['min', 'max', 'count'])
        result = result.sort_values(['Macrosite', 'Priority'],  ascending=[True, False])
    except Exception as e:
        # for debugging
        import pdb; pdb.set_trace()
        print(e)

    images = result.reset_index()
    return images.values.tolist()

def _get_images_to_annotate(request):
        filterset = {'start_date': None,
                            'end_date': None,
                            'station':None,
                            'macrosite':None,
                            'annotator':request.user
                            }

        # Get the images to annotate (uncertain images). Check raw sql to see how this is done
        # Get the images to not consider to annotate (images touched by user). Check raw sql to see how this is done
        uncertain_images = get_uncertain_images(filterset)
        ignore_images = get_images_to_ignore(request.user.id)

        # Convert images raw sql objects to set of images
        ignore_images_s=set([ui.id for ui in ignore_images])

        # Skipped image by the user. Not to be considered for annotation here.
        image_skiped = Image.objects.filter(bbox_skipped_by__id=filterset['annotator'].id).values_list('id', flat=True)
        ignore_images_s.add(image_skiped)

        # Remove images to ignore from uncertain images
        # Resulting uncertain images need to be annotated
        images = [ui for ui in uncertain_images if ui.id not in ignore_images_s]
        return images


@method_decorator(csrf_exempt, name='dispatch')
class PrioritizedImagesJsonView(View):
    def get(self, request, *args, **kwargs):
        images = get_prioritized_images()
        data = {
            'result': 'success',
            # 'message': 'Message: Prioritized images',
            'prioritezed_images':_pd_group_images(images)
        }
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class UncertainImagesJsonView(View):
    def get(self, request, *args, **kwargs):
        images = _get_images_to_annotate(request)
        data = {
            'result': 'success',
            # 'message': 'Message: Prioritized images',
            'prioritezed_images':_pd_group_images(images)
        }
        return JsonResponse(data)




class WorkflowStateView(TemplateView):
    """
    A view to show the workflow state of the images.
    It has the Ajax calls to build the tables of each step in the workflow.
    """
    template_name = "explore/workflow_state.html"

    def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context["total_images"] = Image.get_total_images()
            context["total_images_processed"] = Image.get_total_images_processed()
            context["total_images_not_processed"] = Image.get_total_images_not_processed()
            context["untouched_images"] = Image.get_untouched_images()
            return context
