

from django.views.generic.list import ListView
from images.models.annotation import Species
from images.models.image import Image

from django.db import reset_queries
from django.db import connection

import sys


def ts_by_specie_macro_micro(specie):
    sp = Species.objects.raw('''
								SELECT MIN(is2.id::TEXT) AS id,
                                    MIN(ii.trigger_timestamp::date) AS exif_dt,
                                    lm2.name AS macrosite,
                                    lm.name AS microsite,
                                    MIN(iu.date_retrieved::date) AS uploaded_dt,
                                    MIN(is2.created::date) AS species_annot_dt,
                                    lc.latitude AS latitude,
                                    lc.longitude AS longitude,
                                    COUNT(1) AS total
                                FROM images_species AS is2
                                RIGHT JOIN images_speciesname is3
                                    ON is2.name_id = is3.id
                                INNER JOIN images_annotator AS ia
                                    ON ia.id = is2.created_by_id
                                INNER JOIN images_boundingbox ib
                                    ON is2.bounding_box_id = ib.id
                                INNER JOIN images_image ii
                                    ON ib.image_id = ii.id
                                INNER JOIN images_upload iu
                                    ON ii.upload_id = iu.id
                                INNER JOIN locations_camerastation lc
                                    ON iu.camera_station_id = lc.id
                                INNER JOIN locations_microsite lm
                                    ON lc.micro_site_id = lm.id
                                INNER JOIN locations_macrosite lm2
                                    ON lm.macro_site_id = lm2.id
                                WHERE is3.name = '{}'
                                GROUP BY ii.trigger_timestamp::date, macrosite, microsite,
                                			lc.latitude, lc.longitude
                                ORDER BY ii.trigger_timestamp::date DESC

                    '''.format(specie))
    return sp


def get_images_by(specie, date_sighting, macrosite, microsite):
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
                             """.format(specie, macrosite, microsite, date_sighting))

    return imgs



class SpecieSightingTimeserieView(ListView):
    model = Species
    template_name = 'explore/specie_sighting_timeserie_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.specie_name = self.kwargs['specie']
        self.object_list = ts_by_specie_macro_micro(self.kwargs['specie'])
        context['specie_sighting_timeserie_list'] = self.object_list
        context['specie'] = self.specie_name

        return context



class SpecieSightingImagesView(ListView):
    model = Species
    template_name = 'explore/specie_sighting_images.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        specie = self.request.GET.get('specie', None)
        macrosite = self.request.GET.get('macrosite', None)
        microsite = self.request.GET.get('microsite', None)
        date_sighting = self.request.GET.get('date_sighting', None)


        images_list = get_images_by(specie, date_sighting, macrosite, microsite)
        context['images_list'] = images_list
        context['specie'] = specie
        context['macrosite'] = macrosite
        context['microsite'] = microsite
        context['date_sighting'] = date_sighting

        return context