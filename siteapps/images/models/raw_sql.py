def get_object_annotation_images(
    annotator=None, start_date=None, end_date=None, station=None, macrosite=None, queue_size=0
):
    from images.models.image import Image

    """
    This function contains the raw SQL query for the Object annotation pipeline.
    """
    start_date = (
        "AND images.trigger_timestamp >= '{}'".format(start_date)
        if start_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    end_date = (
        "AND images.trigger_timestamp <= '{}'".format(end_date)
        if end_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    macrosite = (
        "AND location_macro.name = '{}'".format(macrosite)
        if macrosite
        else "AND location_macro.name = location_macro.name"
    )
    station = (
        "AND location_camera.station_id = '{}'".format(station)
        if station
        else "AND location_camera.station_id = location_camera.station_id"
    )

    """
    The following sequence of queries first collects all the bounding boxes
    that need to be voted on. Either because they're new, or their accept / reject
    threshold has not been met yet.
    While doing this we filter based on timestamp / macro_station / camera_station if they're passed in.
    Then we filter out annotations by staff users because their vote automatically counts
    as a universal accept / reject.
    We also filter out the images that have already been voted on by the currently logged in user.
    """

    imgs = Image.objects.raw(
        """
            /* All accepted Bounding Boxes */
            WITH bb_accepted_all AS
            (
                SELECT COUNT(1) AS total_count,
                    ibb_accepted.boundingbox_id AS group_column
                FROM images_boundingbox_accepted_by AS ibb_accepted
                GROUP BY group_column
            ),
            /* All rejected Bounding Boxes */
            bb_rejected_all AS
            (
                SELECT COUNT(1) AS total_count,
                        ibb_rejected.boundingbox_id AS group_column
                FROM images_boundingbox_rejected_by AS ibb_rejected
                GROUP BY group_column
            ),
            /*
            * Uncertain BBs, this is the target.
            * Perform a set operation with accepted and rejected grouped BBs.
            * BBs between -1 and 1 (accepted - rejected votes) are uncertain.
            */
            bb_uncertain AS
            (
                SELECT bbox.id AS bb_id,
                    COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) AS difference
                FROM images_boundingbox as bbox
                LEFT JOIN bb_accepted_all
                    ON bbox.id = bb_accepted_all.group_column
                LEFT JOIN bb_rejected_all
                    ON bbox.id = bb_rejected_all.group_column
                WHERE COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) < 2
                    AND COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) > -2
            ),
            /*
            * Get the images.
            * The order or operations below matters,
            * to filter from the smallest group to the largest
            */
            result_set AS (
                SELECT DISTINCT images.id AS id,
                    images.trigger_timestamp AS ts,
                    image_upload.priority AS priority,
                    location_macro.name AS macrosite,
                    location_camera.id AS camera_station
                FROM bb_uncertain
                LEFT JOIN images_boundingbox AS ib
                    ON ib.id = bb_uncertain.bb_id
                LEFT JOIN images_image AS images
                    ON images.id = ib.image_id
                INNER JOIN images_upload AS image_upload
                    ON images.upload_id = image_upload.id
                INNER JOIN locations_camerastation AS location_camera
                    ON image_upload.camera_station_id = location_camera.id
                INNER JOIN locations_microsite AS location_micro
                    ON location_camera.micro_site_id = location_micro.id
                INNER JOIN locations_macrosite AS location_macro
                    ON location_micro.macro_site_id = location_macro.id
                WHERE images.processed = TRUE
                {start_date} {end_date} {macrosite} {station}
            ),
            /*
            * Return images touched by a user.
            * Images that should be ignored at anytime.
            */
            ignore_annotators AS
            (
                SELECT ia.id AS id
                FROM users_user AS uu
                INNER JOIN images_annotator AS ia
                    ON ia.human_id = uu.id
                WHERE uu.is_staff
                    OR uu.id = '{annotator_id}'
            ),
            ignore_bbs AS
            (
                SELECT ibab.boundingbox_id
                FROM images_boundingbox_accepted_by ibab
                INNER JOIN ignore_annotators AS ia
                    ON ibab.annotator_id = ia.id
                UNION
                SELECT ibrb.boundingbox_id
                FROM images_boundingbox_rejected_by ibrb
                INNER JOIN ignore_annotators AS ia
                    ON ibrb.annotator_id = ia.id
            ),
            ignore_images AS
            (
                SELECT DISTINCT(image_id) as id
                FROM ignore_bbs
                INNER JOIN images_boundingbox AS ib
                    ON ib.id = ignore_bbs.boundingbox_id
            )
            SELECT
                rs.id,
                rs.ts,
                rs.priority,
                rs.macrosite,
                rs.camera_station
            FROM result_set rs
            WHERE NOT EXISTS (
                SELECT id
                FROM ignore_images ii
                WHERE ii.id = rs.id
            )
            ORDER BY priority DESC, camera_station, ts DESC
            LIMIT {queue_size}
        """.format(
            start_date=start_date,
            end_date=end_date,
            macrosite=macrosite,
            station=station,
            annotator_id=annotator.id,
            queue_size=queue_size,
        )
    )
    return imgs


def get_prioritized_images(priority=None, start_date=None, end_date=None, station=None, macrosite=None):
    from images.models.image import Image

    """
    Prioritized images.
    Images still not touched by any annotator.
    No bounding box accepted or rejected.
    """

    imgs = Image.objects.raw(
        """
            WITH images_not_touched AS
            (
                SELECT DISTINCT(image_id)
                FROM images_boundingbox
                WHERE NOT EXISTS (
                    SELECT boundingbox_id
                    FROM images_boundingbox_accepted_by AS iba
                    WHERE iba.boundingbox_id = images_boundingbox.id
                        UNION
                    SELECT boundingbox_id
                    FROM images_boundingbox_rejected_by AS ibr
                    WHERE ibr.boundingbox_id = images_boundingbox.id
                )
            ),
            images_details AS
            (
                SELECT images.id,
                    images.trigger_timestamp AS ts,
                    image_upload.priority AS priority,
                    location_macro.name AS macrosite,
                    location_camera.station_id AS station
                FROM images_image AS images
                INNER JOIN images_not_touched AS images_nt
                    ON images_nt.image_id = images.id
                INNER JOIN images_upload AS image_upload
                    ON image_upload.id = images.upload_id
                LEFT JOIN locations_camerastation AS location_camera
                    ON image_upload.camera_station_id = location_camera.id
                LEFT JOIN locations_microsite AS location_micro
                    ON location_camera.micro_site_id = location_micro.id
                LEFT JOIN locations_macrosite AS location_macro
                    ON location_micro.macro_site_id = location_macro.id
            )
            SELECT * FROM images_details
            --WHERE priority = '{}'
            --LIMIT 200
            ;
            """  # .format(priority)
    )
    return imgs


def get_species_annotated(species_ids):
    from images.models.image import Image

    """
    All images with species annotated.
    """
    imgs = Image.objects.raw(
        """
        WITH species_annotated AS
        (
            SELECT images.id,
                images.trigger_timestamp AS ts,
                image_upload.priority AS priority,
                location_macro.name AS macrosite,
                location_camera.station_id AS station,
                speciesname.name AS species
            FROM images_species AS species
            LEFT JOIN images_boundingbox AS image_bb
                ON species.bounding_box_id = image_bb.id
            LEFT JOIN images_image AS images
                ON image_bb.image_id = images.id
            LEFT JOIN images_upload AS image_upload
                ON images.upload_id = image_upload.id
            LEFT JOIN locations_camerastation AS location_camera
                ON image_upload.camera_station_id = location_camera.id
            LEFT JOIN locations_microsite AS location_micro
                ON location_camera.micro_site_id = location_micro.id
            LEFT JOIN locations_macrosite AS location_macro
                ON location_micro.macro_site_id = location_macro.id
            LEFT JOIN images_speciesname speciesname
                ON species.name_id = speciesname.id
            WHERE species.name_id IN {}
            --LIMIT 100
        )
        SELECT * FROM species_annotated
    """.format(
            species_ids
        )
    )
    return imgs


def get_images_to_ignore(annotator=None):
    from images.models.image import Image

    """
    Return images touched by a user via BoundingBoxes.
    Also include images that were toucjhed by staff.
    """

    annotator = "OR uu.id='{}'".format(annotator) if annotator else ""

    imgs = Image.objects.raw(
        """
            /*
            * Return images touched by a user.
            * Images that should be ignored at anytime.
            */
            WITH ignore_annotators AS
            (
                SELECT ia.id AS id
                FROM users_user AS uu
                INNER JOIN	images_annotator AS ia
                    ON ia.human_id = uu.id
                WHERE uu.is_staff
                    {}
            ),
            ignore_bbs AS
            (
                SELECT ibab.boundingbox_id
                FROM images_boundingbox_accepted_by ibab
                INNER JOIN ignore_annotators AS ia
                    ON ibab.annotator_id = ia.id
                UNION
                SELECT ibrb.boundingbox_id
                FROM images_boundingbox_rejected_by ibrb
                INNER JOIN ignore_annotators AS ia
                    ON ibrb.annotator_id = ia.id
            ),
            ignore_images AS
            (
                SELECT DISTINCT(image_id) as id
                FROM ignore_bbs
                INNER JOIN	images_boundingbox AS ib
                    ON ib.id = ignore_bbs.boundingbox_id
            )
            SELECT * FROM ignore_images
        """.format(
            annotator
        )
    )
    return imgs


def get_uncertain_images(annotator=None, start_date=None, end_date=None, station=None, macrosite=None):
    from images.models.image import Image

    """
    These are images that have been accepted and rejected by
    the difference of one, in the number of annotators.
    See more comments inline
    """

    start_date = (
        "AND images.trigger_timestamp >= '{}'".format(start_date)
        if start_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    end_date = (
        "AND images.trigger_timestamp <= '{}'".format(end_date)
        if end_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    macrosite = (
        "AND location_macro.name = '{}'".format(macrosite)
        if macrosite
        else "AND location_macro.name = location_macro.name"
    )
    station = (
        "AND location_camera.station_id = '{}'".format(station)
        if station
        else "AND location_camera.station_id = location_camera.station_id"
    )

    imgs = Image.objects.raw(
        """
            /* All accepted Bounding Boxes */
            WITH bb_accepted_all AS
            (
                SELECT COUNT(1) AS total_count,
                    ibb_accepted.boundingbox_id AS group_column
                FROM images_boundingbox_accepted_by AS ibb_accepted
                GROUP BY group_column
            ),
            /* All rejected Bounding Boxes */
            bb_rejected_all AS
            (
                SELECT COUNT(1) AS total_count,
                        ibb_rejected.boundingbox_id AS group_column
                FROM images_boundingbox_rejected_by AS ibb_rejected
                GROUP BY group_column
            ),
            /*
            * Uncertain BBs, this is the target.
            * Perform a set operation with accepted and rejected grouped BBs.
            * BBs between -1 and 1 (accepted - rejected votes) are uncertain.
            */
            bb_uncertain AS
            (
                SELECT bb_accepted_all.group_column AS bb_id,
                    COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) AS difference
                FROM bb_accepted_all
                INNER JOIN bb_rejected_all
                    ON bb_accepted_all.group_column = bb_rejected_all.group_column
                WHERE COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) < 2
                    AND COALESCE(bb_accepted_all.total_count, 0) -
                        COALESCE(bb_rejected_all.total_count, 0) > -2
            ),
            /*
            * Get the images.
            * The order or operations below matters,
            * to filter from the smallest group to the largest
            */
            images_details AS (
                SELECT DISTINCT images.id AS id,
                    images.trigger_timestamp AS ts,
                    image_upload.priority AS priority,
                    location_macro.name AS macrosite,
                    location_camera.station_id AS station
                FROM bb_uncertain
                LEFT JOIN images_boundingbox AS ib
                    ON ib.id = bb_uncertain.bb_id
                LEFT JOIN images_image AS images
                    ON images.id = ib.image_id
                INNER JOIN images_upload AS image_upload
                    ON images.upload_id = image_upload.id
                INNER JOIN locations_camerastation AS location_camera
                    ON image_upload.camera_station_id = location_camera.id
                INNER JOIN locations_microsite AS location_micro
                    ON location_camera.micro_site_id = location_micro.id
                INNER JOIN locations_macrosite AS location_macro
                    ON location_micro.macro_site_id = location_macro.id
                WHERE 1 = 1
                {} {} {} {}
                ORDER BY priority DESC, ts DESC
            )
            SELECT * FROM images_details
        """.format(
            start_date, end_date, macrosite, station
        )
    )
    return imgs


def get_species_to_annotate(annotator=None, start_date=None, end_date=None, station=None, macrosite=None, queue_size=0):
    from images.models.image import Image

    """
    This function contains the raw SQL query for the Species annotation pipeline.
    """
    start_date = (
        "AND images.trigger_timestamp >= '{}'".format(start_date)
        if start_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    end_date = (
        "AND images.trigger_timestamp <= '{}'".format(end_date)
        if end_date
        else "AND images.trigger_timestamp = images.trigger_timestamp"
    )
    macrosite = (
        "AND location_macro.name = '{}'".format(macrosite)
        if macrosite
        else "AND location_macro.name = location_macro.name"
    )
    station = (
        "AND location_camera.station_id = '{}'".format(station)
        if station
        else "AND location_camera.station_id = location_camera.station_id"
    )
    queue_size = "LIMIT {}".format(queue_size) if queue_size > 0 else ""

    imgs = Image.objects.raw(
        """
        WITH animal_images_touched AS
        (
            SELECT image_id
            FROM images_boundingbox AS ib
            RIGHT JOIN(
                SELECT boundingbox_id
                FROM images_boundingbox_accepted_by AS iba
                    UNION
                SELECT boundingbox_id
                FROM images_boundingbox_rejected_by AS ibr
            ) AS bbs
                ON bbs.boundingbox_id = ib.id
            INNER JOIN images_category AS ic
                ON ic.bounding_box_id = ib.id
            WHERE ic.name = 'animal'
        ),
        images_details AS
        (
            SELECT images.id,
                images.trigger_timestamp AS ts,
                image_upload.priority AS priority,
                location_macro.name AS macrosite,
                location_camera.station_id AS station
            FROM images_image AS images
            RIGHT JOIN animal_images_touched AS images_t
                ON images_t.image_id = images.id
            LEFT JOIN images_upload AS image_upload
                ON image_upload.id = images.upload_id
            LEFT JOIN locations_camerastation AS location_camera
                ON image_upload.camera_station_id = location_camera.id
            LEFT JOIN locations_microsite AS location_micro
                ON location_camera.micro_site_id = location_micro.id
            LEFT JOIN locations_macrosite AS location_macro
                ON location_micro.macro_site_id = location_macro.id
            WHERE images.processed = TRUE
            {start_date} {end_date} {macrosite} {station}
            {queue_size}
        )
        SELECT * FROM images_details
        """.format(
            start_date=start_date,
            end_date=end_date,
            macrosite=macrosite,
            station=station,
            queue_size=queue_size,
        )
    )
    return imgs
