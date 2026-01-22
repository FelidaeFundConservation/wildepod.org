from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection, reset_queries
from django.views.generic.list import ListView

from siteapps.images.models.annotation import Species, SpeciesName
from siteapps.images.models.image import Image


def _build_filter_clauses(macrosite=None, microsite=None, station=None):
    """
    Build common WHERE clause filters for species queries.
    Returns a tuple of (macrosite_clause, microsite_clause, station_clause).
    """
    macrosite_clause = (
        "AND location_macro.name = '{}'".format(macrosite)
        if macrosite
        else "AND location_macro.name = location_macro.name"
    )
    microsite_clause = (
        "AND location_micro.name = '{}'".format(microsite)
        if microsite
        else "AND location_micro.name = location_micro.name"
    )
    station_clause = (
        "AND location_camera.station_id = '{}'".format(station)
        if station
        else "AND location_camera.station_id = location_camera.station_id"
    )
    return macrosite_clause, microsite_clause, station_clause


def _get_base_joins():
    """
    Get the common JOIN clauses used across species queries.
    Returns a tuple of (sqlite_joins, postgres_joins).
    """
    # Common INNER JOINs (same for both databases)
    common_joins = """INNER JOIN images_annotator AS annotator
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
                ON location_micro.macro_site_id = location_macro.id"""

    # SQLite uses LEFT JOIN
    sqlite_joins = (
        """LEFT JOIN images_species AS species
                ON species.name_id = speciesname.id
            """
        + common_joins
    )

    # PostgreSQL uses RIGHT JOIN
    postgres_joins = (
        """RIGHT JOIN images_speciesname speciesname
                ON species.name_id = speciesname.id
            """
        + common_joins
    )

    return sqlite_joins, postgres_joins


def ts_by_species(
    species, macrosite=None, microsite=None, station=None, sort_by=None, sort_dir="desc", limit=None, offset=None
):
    """
    Get species sighting timeseries data with pagination and sorting.
    """
    macrosite_clause, microsite_clause, station_clause = _build_filter_clauses(macrosite, microsite, station)

    # Map frontend sort keys to SQL column names
    sort_map = {
        "exif_dt": "exif_dt",
        "uploaded_dt": "uploaded_dt",
        "species_annot_dt": "species_annot_dt",
        "macrosite": "macrosite",
        "station_id": "station_id",
        "latitude": "latitude",
        "longitude": "longitude",
        "total": "total",
    }

    # Validate sort parameters
    if sort_by and sort_by in sort_map:
        order_column = sort_map[sort_by]
    else:
        # Default sort by trigger timestamp descending
        order_column = "exif_dt"
        sort_dir = "desc"

    # Validate sort direction
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    order_by_clause = f"ORDER BY {order_column} {sort_direction}"

    # Add LIMIT and OFFSET if provided
    limit_offset_clause = ""
    if limit is not None:
        limit_offset_clause = f"LIMIT {int(limit)}"
        if offset is not None:
            limit_offset_clause += f" OFFSET {int(offset)}"

    sqlite_joins, postgres_joins = _get_base_joins()

    # Use different SQL depending on DB backend
    if connection.vendor == "sqlite":
        sql = """
                            SELECT MIN(CAST(species.id AS TEXT)) AS id,
                                MIN(DATE(image.trigger_timestamp)) AS exif_dt,
                                location_macro.name AS macrosite,
                                location_micro.name AS microsite,
                                location_camera.station_id AS station_id,
                                MIN(DATE(image_upload.date_retrieved)) AS uploaded_dt,
                                MIN(DATE(species.created)) AS species_annot_dt,
                                location_camera.latitude AS latitude,
                                location_camera.longitude AS longitude,
                                COUNT(1) AS total
                            FROM images_speciesname AS speciesname
                            {joins}
                            WHERE speciesname.name = '{species}'
                                {macrosite} {microsite} {station}
                            GROUP BY DATE(image.trigger_timestamp), macrosite, microsite,
                                        station_id, location_camera.latitude,
                                        location_camera.longitude
                            {order_by}
                            {limit_offset}
                    """.format(
            joins=sqlite_joins,
            species=species,
            macrosite=macrosite_clause,
            microsite=microsite_clause,
            station=station_clause,
            order_by=order_by_clause,
            limit_offset=limit_offset_clause,
        )
    else:
        sql = """
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
                            {joins}
                            WHERE speciesname.name = '{species}'
                                {macrosite} {microsite} {station}
                            GROUP BY image.trigger_timestamp::date, macrosite, microsite,
                                        station_id, location_camera.latitude,
                                        location_camera.longitude
                            {order_by}
                            {limit_offset}
                    """.format(
            joins=postgres_joins,
            species=species,
            macrosite=macrosite_clause,
            microsite=microsite_clause,
            station=station_clause,
            order_by=order_by_clause,
            limit_offset=limit_offset_clause,
        )

    sp = Species.objects.raw(sql)
    return sp


def count_species_sightings(species, macrosite=None, microsite=None, station=None):
    """
    Get the total count of species sightings for pagination.
    This runs a COUNT query without LIMIT/OFFSET for efficiency.
    """
    macrosite_clause, microsite_clause, station_clause = _build_filter_clauses(macrosite, microsite, station)
    sqlite_joins, postgres_joins = _get_base_joins()

    if connection.vendor == "sqlite":
        sql = """
            SELECT COUNT(*) as count
            FROM (
                SELECT MIN(CAST(species.id AS TEXT)) AS id,
                       location_macro.name AS macrosite,
                       location_micro.name AS microsite,
                       location_camera.station_id AS station_id
                FROM images_speciesname AS speciesname
                {joins}
                WHERE speciesname.name = '{species}'
                    {macrosite} {microsite} {station}
                GROUP BY DATE(image.trigger_timestamp), macrosite, microsite,
                            station_id, location_camera.latitude,
                            location_camera.longitude
            )
        """.format(
            joins=sqlite_joins,
            species=species,
            macrosite=macrosite_clause,
            microsite=microsite_clause,
            station=station_clause,
        )
    else:
        sql = """
            SELECT COUNT(*) as count
            FROM (
                SELECT MIN(species.id::TEXT) AS id,
                       location_macro.name AS macrosite,
                       location_micro.name AS microsite,
                       location_camera.station_id AS station_id
                FROM images_species AS species
                {joins}
                WHERE speciesname.name = '{species}'
                    {macrosite} {microsite} {station}
                GROUP BY image.trigger_timestamp::date, macrosite, microsite,
                            station_id, location_camera.latitude,
                            location_camera.longitude
            ) AS subquery
        """.format(
            joins=postgres_joins,
            species=species,
            macrosite=macrosite_clause,
            microsite=microsite_clause,
            station=station_clause,
        )

    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
        return row[0] if row else 0


def get_images_by(species, date_sighting, macrosite, microsite):
    """
    Get images for a specific species on a specific date and location.
    """
    # Common JOINs for this simpler query (no annotator)
    common_joins = """INNER JOIN images_boundingbox AS image_bb
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
                    ON location_micro.macro_site_id = location_macro.id"""

    # Escape single quotes in microsite name
    microsite_safe = microsite.replace("'", "''")

    if connection.vendor == "sqlite":
        sql = """
                                SELECT image.id, image.trigger_timestamp AS exif,
                                image.thumbnail_gcloud_path AS thumbnail
                                FROM images_speciesname AS species_name
                                LEFT JOIN images_species
                                    ON images_species.name_id = species_name.id
                                {joins}
                                WHERE species_name.name = '{species}'
                                    AND location_macro.name = '{macrosite}'
                                    AND location_micro.name = '{microsite}'
                                    AND DATE(image.trigger_timestamp) = '{date_sighting}'
                                ORDER BY exif DESC
                             """.format(
            joins=common_joins,
            species=species,
            macrosite=macrosite,
            microsite=microsite_safe,
            date_sighting=date_sighting,
        )
    else:
        sql = """
                                SELECT image.id, image.trigger_timestamp AS exif,
                                image.thumbnail_gcloud_path AS thumbnail
                                FROM images_species
                                RIGHT JOIN images_speciesname AS species_name
                                    ON images_species.name_id = species_name.id
                                {joins}
                                WHERE species_name.name = '{species}'
                                    AND location_macro.name = '{macrosite}'
                                    AND location_micro.name = '{microsite}'
                                    AND image.trigger_timestamp::date = '{date_sighting}'
                                ORDER BY exif DESC
                             """.format(
            joins=common_joins,
            species=species,
            macrosite=macrosite,
            microsite=microsite_safe,
            date_sighting=date_sighting,
        )

    imgs = Image.objects.raw(sql)
    return imgs


class SpeciesSightingTimeseriesView(LoginRequiredMixin, ListView):
    model = Species
    template_name = "explore/species_sighting_timeserie_list.html"
    context_object_name = "species_sighting_timeserie_list"
    paginate_by = None  # We'll handle pagination manually

    def get_paginate_by(self, queryset):
        """
        Allow user to set pagination via 'per_page' query parameter.
        Default is 25, with allowed values of 10, 25, 50, 100, or 'all'.
        """
        per_page = self.request.GET.get("per_page", "25")

        # If user requests 'all', return None to disable pagination
        if per_page.lower() == "all":
            return None

        # Validate and convert to integer
        try:
            per_page_int = int(per_page)
            # Limit to reasonable values
            if per_page_int in [10, 25, 50, 100]:
                return per_page_int
            else:
                # Default to 25 if invalid value
                return 25
        except (ValueError, TypeError):
            # Default to 25 if conversion fails
            return 25

    def get_queryset(self):
        """
        This method is still called by ListView but we'll override the pagination logic.
        Return an empty list since we're handling pagination in get_context_data.
        """
        return []

    def paginate_queryset(self, queryset, page_size):
        """
        Override ListView's pagination to prevent it from paginating our empty queryset.
        We handle pagination manually in get_context_data with SQL LIMIT/OFFSET.
        """
        # Return None to indicate no pagination should be done by ListView
        return (None, None, None, None)

    def get_context_data(self, **kwargs):
        # Don't call super() as it expects pagination data we're not providing
        context = {}

        species = self.kwargs["species"] if "species" in self.kwargs else "Puma"
        macrosite = self.request.GET.get("macrosite", None)
        microsite = self.request.GET.get("microsite", None)
        station = self.request.GET.get("station", None)
        sort_by = self.request.GET.get("sort", None)
        sort_dir = self.request.GET.get("dir", "desc")

        # Get pagination parameters
        per_page = self.get_paginate_by(None)
        current_page = int(self.request.GET.get("page", 1))

        # Calculate LIMIT and OFFSET
        if per_page is None:
            # Show all records
            limit = None
            offset = None
            total_count = count_species_sightings(species, macrosite, microsite, station)
        else:
            # Paginated view
            limit = per_page
            offset = (current_page - 1) * per_page
            total_count = count_species_sightings(species, macrosite, microsite, station)

        # Get the paginated results with LIMIT/OFFSET
        queryset = ts_by_species(
            species=species,
            macrosite=macrosite,
            microsite=microsite,
            station=station,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        )

        # Convert to list for template use
        results_list = list(queryset)

        # Create a page object for template compatibility
        from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator

        if per_page is None:
            # No pagination - create a single "page" with all results
            # Create a dummy paginator with all results
            paginator = Paginator(results_list, total_count or 1)
            try:
                page_obj = paginator.page(1)
            except (EmptyPage, PageNotAnInteger):
                # Fallback if there's an issue
                page_obj = Page(results_list, 1, paginator)
        else:
            # Create paginator with dummy object list equal to total count
            # This allows proper page calculation
            paginator = Paginator(range(total_count), per_page)

            # Validate page number - if invalid, default to 1
            if current_page < 1:
                current_page = 1
            elif current_page > paginator.num_pages:
                current_page = paginator.num_pages if paginator.num_pages > 0 else 1

            # Create Page object directly (bypass validation that checks if object_list has items)
            # We already fetched the correct items from the database with LIMIT/OFFSET
            page_obj = Page(results_list, current_page, paginator)

        # Add to context
        context["species_sighting_timeserie_list"] = results_list
        context["page_obj"] = page_obj
        context["paginator"] = paginator
        context["is_paginated"] = per_page is not None and total_count > per_page

        context["species"] = species
        species_l = [species.name for species in SpeciesName.objects.all().order_by("name")]
        context["species_l"] = species_l

        # Add current per_page value to context for template use
        context["per_page"] = self.request.GET.get("per_page", "25")

        # Add current sort parameters to context
        context["current_sort"] = self.request.GET.get("sort", "exif_dt")
        context["current_dir"] = self.request.GET.get("dir", "desc")

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
