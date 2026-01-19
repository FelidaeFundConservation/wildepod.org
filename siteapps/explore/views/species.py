from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection, reset_queries
from django.views.generic.list import ListView
from images.models.annotation import Species, SpeciesName
from images.models.image import Image


def _build_location_filters(macrosite=None, microsite=None, station=None):
    """Return SQL filter snippets for macrosite/microsite/station."""
    macrosite_filter = (
        "AND location_macro.name = '{}'".format(macrosite)
        if macrosite
        else "AND location_macro.name = location_macro.name"
    )
    microsite_filter = (
        "AND location_micro.name = '{}'".format(microsite)
        if microsite
        else "AND location_micro.name = location_micro.name"
    )
    station_filter = (
        "AND location_camera.station_id = '{}'".format(station)
        if station
        else "AND location_camera.station_id = location_camera.station_id"
    )
    return macrosite_filter, microsite_filter, station_filter


def _cast_to_text(field, vendor):
    """Cast field to TEXT based on database vendor."""
    return f"{field}::TEXT" if vendor == "postgresql" else f"CAST({field} AS TEXT)"


def _cast_to_date(field, vendor):
    """Cast field to date/datetime based on database vendor."""
    return f"{field}::date" if vendor == "postgresql" else f"DATETIME({field})"


def _ts_query(vendor):
    """Build timeseries query for specified database vendor."""
    id_cast = _cast_to_text("species.id", vendor)
    exif_cast = _cast_to_date("image.trigger_timestamp", vendor)
    uploaded_cast = _cast_to_date("image_upload.date_retrieved", vendor)
    created_cast = _cast_to_date("species.created", vendor)

    # PostgreSQL supports RIGHT JOIN, SQLite needs INNER JOIN with reversed order
    if vendor == "postgresql":
        from_clause = """FROM images_species AS species
        RIGHT JOIN images_speciesname speciesname
               ON species.name_id = speciesname.id"""
        group_by = f"{exif_cast}, macrosite, microsite, station_id, location_camera.latitude, location_camera.longitude"
        order_by = f"{exif_cast} DESC"
    else:
        from_clause = """FROM images_speciesname speciesname
        INNER JOIN images_species AS species
                ON species.name_id = speciesname.id"""
        group_by = f"DATE(image.trigger_timestamp), macrosite, microsite, station_id, location_camera.latitude, location_camera.longitude"
        order_by = f"MIN(DATETIME(image.trigger_timestamp)) DESC"

    return f"""
        SELECT MIN({id_cast}) AS id,
               MIN({exif_cast}) AS exif_dt,
               location_macro.name AS macrosite,
               location_micro.name AS microsite,
               location_camera.station_id AS station_id,
               MIN({uploaded_cast}) AS uploaded_dt,
               MIN({created_cast}) AS created,
               location_camera.latitude AS latitude,
               location_camera.longitude AS longitude,
               COUNT(1) AS total
        {from_clause}
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
        WHERE speciesname.name = '{{0}}'
          {{1}} {{2}} {{3}}
        GROUP BY {group_by}
        ORDER BY {order_by}
    """


def ts_by_species(species, macrosite=None, microsite=None, station=None):
    macrosite_filter, microsite_filter, station_filter = _build_location_filters(macrosite, microsite, station)

    sql = _ts_query(connection.vendor).format(species, macrosite_filter, microsite_filter, station_filter)

    sp = Species.objects.raw(sql)

    # Convert SQLite string datetimes to datetime objects for template filters
    if connection.vendor == "sqlite":
        sp_list = list(sp)
        for item in sp_list:
            if item.exif_dt and isinstance(item.exif_dt, str):
                try:
                    item.exif_dt = datetime.fromisoformat(item.exif_dt.replace(" ", "T"))
                except (ValueError, AttributeError):
                    pass
            if item.uploaded_dt and isinstance(item.uploaded_dt, str):
                try:
                    item.uploaded_dt = datetime.fromisoformat(item.uploaded_dt.replace(" ", "T"))
                except (ValueError, AttributeError):
                    pass
            if item.created and isinstance(item.created, str):
                try:
                    item.created = datetime.fromisoformat(item.created.replace(" ", "T"))
                except (ValueError, AttributeError):
                    pass
        return sp_list

    return sp


def _images_query(vendor):
    """Build images query for specified database vendor."""
    # PostgreSQL supports RIGHT JOIN, SQLite needs INNER JOIN with reversed order
    if vendor == "postgresql":
        from_clause = """FROM images_species
        RIGHT JOIN images_speciesname AS species_name
            ON images_species.name_id = species_name.id"""
        date_filter = "image.trigger_timestamp::date = '{3}'"
    else:
        from_clause = """FROM images_speciesname AS species_name
        INNER JOIN images_species
            ON images_species.name_id = species_name.id"""
        date_filter = "DATE(image.trigger_timestamp) = '{3}'"

    return f"""
        SELECT image.id, image.trigger_timestamp AS exif,
               image.thumbnail_gcloud_path AS thumbnail
        {from_clause}
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
        WHERE species_name.name = '{{0}}'
            AND location_macro.name = '{{1}}'
            AND location_micro.name = '{{2}}'
            AND {date_filter}
        ORDER BY exif DESC
    """


def get_images_by(species, date_sighting, macrosite, microsite):
    sql = _images_query(connection.vendor).format(species, macrosite, microsite.replace("'", "''"), date_sighting)
    imgs = Image.objects.raw(sql)
    return imgs


class SpeciesSightingTimeseriesView(LoginRequiredMixin, ListView):
    model = Species
    template_name = "explore/species_sighting_timeserie_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        species = self.kwargs["species"] if "species" in self.kwargs else "Puma"
        macrosite = self.request.GET.get("macrosite", None)
        microsite = self.request.GET.get("microsite", None)
        station = self.request.GET.get("station", None)

        self.object_list = ts_by_species(species=species, macrosite=macrosite, microsite=microsite, station=station)

        context["species_sighting_timeserie_list"] = self.object_list
        context["species"] = species

        species_l = [species.name for species in SpeciesName.objects.all().order_by("name")]

        context["species_l"] = species_l
        return context


class SpeciesSightingImagesView(LoginRequiredMixin, ListView):
    model = Species
    template_name = "explore/species_sighting_images.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        species = self.request.GET.get("species", None)
        macrosite = self.request.GET.get("macrosite", None)
        microsite = self.request.GET.get("microsite", None)
        station = self.request.GET.get("station", None)
        date_sighting = self.request.GET.get("date_sighting", None)

        images_list = get_images_by(species, date_sighting, macrosite, microsite)
        context["images_list"] = images_list
        context["species"] = species
        context["macrosite"] = macrosite
        context["microsite"] = microsite
        context["station"] = station
        context["date_sighting"] = date_sighting

        return context
