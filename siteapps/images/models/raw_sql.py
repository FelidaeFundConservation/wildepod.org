from images.models.image import Image


def get_object_annotation_images(annotator=None, start_date=None, end_date=None, station=None, macrosite=None, queue_size=0):
    """
    This function contains the raw SQL query for the Object annotation pipeline. 
    """
    start_date = ("AND images.trigger_timestamp >= '{}'".format(start_date)
                    if start_date else "AND images.trigger_timestamp = images.trigger_timestamp")
    end_date = ("AND images.trigger_timestamp <= '{}'".format(end_date)
                    if end_date else "AND images.trigger_timestamp = images.trigger_timestamp")
    macrosite = ("AND location_macro.name = '{}'".format(macrosite)
                    if macrosite   else "AND location_macro.name = location_macro.name")
    station = ("AND location_camera.station_id = '{}'".format(station)
                    if station else "AND location_camera.station_id = location_camera.station_id"
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

    imgs = Image.objects.raw("""
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
                    location_macro.name AS macrosite
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
                INNER JOIN	images_annotator AS ia
                    ON ia.human_id = uu.id
                WHERE uu.is_staff
                    OR uu.is_expert
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
                INNER JOIN	images_boundingbox AS ib
                    ON ib.id = ignore_bbs.boundingbox_id
            )
            SELECT 
                rs.id,
                rs.ts,
                rs.priority,
                rs.macrosite
            FROM result_set rs
            WHERE NOT EXISTS (
                SELECT id
                FROM ignore_images ii
                WHERE ii.id = rs.id
            )
            ORDER BY priority DESC, ts DESC
            LIMIT {queue_size}
        """.format(start_date=start_date, end_date=end_date, macrosite=macrosite, 
                   station=station, annotator_id=annotator.id, queue_size=queue_size)
    )
    return imgs