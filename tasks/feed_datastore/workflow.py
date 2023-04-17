"""
This script updates the workflow documents in the datastore/firebase.
"""

import datetime
import pandas as pd
import os, sys, json, django
from datetime import timedelta


BASE_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, '../../')))
sys.path.append(os.path.join(BASE_DIR, 'siteapps'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from django.conf import settings
from images.models.image import Image
from images.models.raw_sql import get_prioritized_images, get_uncertain_images, get_images_to_ignore



client = settings.DATASTORE_CLIENT
client.namespace='workflow'

def totals_document():
    """ Update the totals document in the workflow collection"""
    # Get workflow collection
    c_key = client.key('total', 'workflow')
    totals = settings.DATASTORE_CLIENT.get(c_key)

    try:
        # Update totals document
        payload = {
            "blank_annotation_images": Image.get_untouched_images(),
            "human_behavior": 0,
            "not_processed_images": Image.get_total_images_not_processed(),
            "processed_images": Image.get_total_images_processed(),
            "species_annotation": 0,
            "uncertain_annotation_images": 0,
            "uploaded_images": Image.get_total_images(),
            "last_update": datetime.datetime.now()
        }
        totals.update(payload)
        client.put(totals)
    except Exception as e:
        print(e)
        return


def _pd_group_images(images):
    """
    Group the images objects by macrosite and camera station
    using pandas
    """
    df = pd.DataFrame([{'Macrosite': i.macrosite,\
                        'Priority': i.priority, \
                        'Station': i.station, \
                        'Trigger': i.ts,} for i in images])

    try:
        result = df.groupby(['Macrosite', 'Station', 'Priority'])['Trigger'].agg(['min', 'max', 'count'])

        # Before serialize date, increase for max and decrease for min,
        # to avoid loose days in the range.
        result['min'] = result['min'] - timedelta(days=1)
        result['max'] = result['max'] + timedelta(days=1)

        # Serialize dates
        result['min'] = result['min'].dt.strftime('%Y-%m-%d')
        result['max'] = result['max'].dt.strftime('%Y-%m-%d')
        result = result.sort_values(['Macrosite', 'Station', 'Priority'],  ascending=[True, False])
    except Exception as e:
        # import pdb; pdb.set_trace()
        print(e)

    images = result.reset_index()
    return images.values.tolist()




def blank_annotation_images():
    images = get_prioritized_images()
    blank_annotation_images = _pd_group_images(images)
    serialized_bai = json.dumps(blank_annotation_images, default=str)

    # Get workflow collection
    c_key = client.key('blank_annotation', 'workflow')
    blank_annotation = settings.DATASTORE_CLIENT.get(c_key)

    try:
        # Update blank_annotation_images document
        payload = {
            "data": serialized_bai,
            "last_update": datetime.datetime.now()
        }
        blank_annotation.update(payload)
        client.put(blank_annotation)
    except Exception as e:
        print(e)
        return





def _get_images_to_annotate():
        # Get the images to annotate (uncertain images). Check raw sql to see how this is done
        # Get the images to not consider to annotate (images touched by user). Check raw sql to see how this is done
        uncertain_images = get_uncertain_images()
        ignore_images = get_images_to_ignore()

        # Convert images raw sql objects to set of images
        ignore_images_s=set([ui.id for ui in ignore_images])

        # Remove images to ignore from uncertain images
        # Resulting uncertain images need to be annotated
        images = [ui for ui in uncertain_images if ui.id not in ignore_images_s]
        return images


def uncertain_images():
    images = _get_images_to_annotate()
    uncertain_images = _pd_group_images(images)
    serialized_ui = json.dumps(uncertain_images, default=str)

    # Get workflow collection
    c_key = client.key('uncertain_images', 'workflow')
    uncertain_images = settings.DATASTORE_CLIENT.get(c_key)

    try:
        # Update uncertain_images document
        payload = {
            "data": serialized_ui,
            "last_update": datetime.datetime.now()
        }
        uncertain_images.update(payload)
        client.put(uncertain_images)
    except Exception as e:
        print(e)
        return



if __name__ == '__main__':
    totals_document()
    uncertain_images()
    blank_annotation_images()

