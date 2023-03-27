from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from images.models.annotation import Species, SpeciesName
from images.models.image import Image

from django.db import reset_queries
from django.db import connection

import sys


def ts_by_species(species, macrosite=None, microsite=None, station=None):

    macrosite = "AND location_macro.name = '{}'".format(macrosite) if macrosite else 'AND location_macro.name = location_macro.name'
    microsite = "AND location_micro.name = '{}'".format(microsite) if microsite else 'AND location_micro.name = location_micro.name'
    station = "AND location_camera.station_id = '{}'".format(station) if station else 'AND location_camera.station_id = location_camera.station_id'

    sp = Species.objects.raw('''
                            SELECT MIN(species.id::TEXT) AS id,
                                MIN(image.trigger_timestamp::date) AS exif_dt,
                                location_macro.name AS macrosite,
                                location_micro.name AS microsite,
                                location_camera.station_id AS station_id,
                                MIN(image_upload.date_retrieved::date) AS uploaded_dt,
                                MIN(species.created::date) AS species_annot_dt,
                                location_camera.latitude AS latitude,
                                location_camera.longitude AS longitude,
                                COUNT(1) AS total
                            FROM images_species AS species
                            RIGHT JOIN images_speciesname speciesname
                                ON species.name_id = speciesname.id
                            INNER JOIN images_annotator AS annotator
                                ON annotator.id = species.created_by_id
                            INNER JOIN images_boundingbox AS image_bb
                                ON species.bounding_box_id = image_bb.id
                            INNER JOIN images_image AS image
                                ON image_bb.image_id = image.id
                            INNER JOIN images_upload AS image_upload
                                ON image.upload_id = image_upload.id
                            INNER JOIN locations_camerastation AS location_camera
                                ON image_upload.camera_station_id = location_camera.id
                            INNER JOIN locations_microsite AS location_micro
                                ON location_camera.micro_site_id = location_micro.id
                            INNER JOIN locations_macrosite AS location_macro
                                ON location_micro.macro_site_id = location_macro.id
                            WHERE speciesname.name = '{}'
                                {} {} {}
                            GROUP BY image.trigger_timestamp::date, macrosite, microsite,
                                        station_id, location_camera.latitude,
                                        location_camera.longitude
                            ORDER BY image.trigger_timestamp::date DESC
                    '''.format(species, macrosite, microsite, station))
    return sp

def get_images_by(species, date_sighting, macrosite, microsite):
    imgs = Image.objects.raw("""
                                SELECT image.id, image.trigger_timestamp AS exif,
                                image.thumbnail_gcloud_path AS thumbnail
                                FROM images_species
                                RIGHT JOIN images_speciesname AS species_name
                                    ON images_species.name_id = species_name.id
                                INNER JOIN images_boundingbox AS image_bb
                                    ON images_species.bounding_box_id = image_bb.id
                                INNER JOIN images_image AS image
                                    ON image_bb.image_id = image.id
                                INNER JOIN images_upload AS image_upload
                                    ON image.upload_id = image_upload.id
                                INNER JOIN locations_camerastation AS location_camera
                                    ON image_upload.camera_station_id = location_camera.id
                                INNER JOIN locations_microsite AS location_micro
                                    ON location_camera.micro_site_id = location_micro.id
                                INNER JOIN locations_macrosite AS location_macro
                                    ON location_micro.macro_site_id = location_macro.id
                                WHERE species_name.name = '{}'
                                    AND location_macro.name = '{}'
                                    AND location_micro.name = '{}'
                                    AND image.trigger_timestamp::date = '{}'
                                ORDER BY exif DESC
                             """.format(species, macrosite, microsite, date_sighting))
    return imgs



class SpeciesSightingTimeserieView(LoginRequiredMixin, ListView):
    model = Species
    template_name = 'explore/species_sighting_timeserie_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        species = self.kwargs['species'] if 'species' in self.kwargs else 'Puma'
        macrosite = self.request.GET.get('macrosite', None)
        microsite = self.request.GET.get('microsite', None)
        station = self.request.GET.get('station', None)

        self.object_list = ts_by_species(species=species, macrosite=macrosite, microsite=microsite, station=station)

        context['species_sighting_timeserie_list'] = self.object_list
        context['species'] = species

        species_l = [species.name for species in SpeciesName.objects.all().order_by('name')]

        # species.remove('Puma')
        # species.remove('Bobcat')
        # species = ['Puma'] + ['Bobcat'] + species

        context['species_l'] = species_l
        return context



class SpeciesSightingImagesView(LoginRequiredMixin, ListView):
    model = Species
    template_name = 'explore/species_sighting_images.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        species = self.request.GET.get('species', None)
        macrosite = self.request.GET.get('macrosite', None)
        microsite = self.request.GET.get('microsite', None)
        station = self.request.GET.get('station', None)
        date_sighting = self.request.GET.get('date_sighting', None)

        images_list = get_images_by(species, date_sighting, macrosite, microsite)
        context['images_list'] = images_list
        context['species'] = species
        context['macrosite'] = macrosite
        context['microsite'] = microsite
        context['station'] = station
        context['date_sighting'] = date_sighting

        return context