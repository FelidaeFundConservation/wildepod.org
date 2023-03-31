from images.models.image import Image

def rawsql_get_blank_annotation():
    imgs = Image.objects.raw("""
                                /* Blank Annotation Pipeline (a.k.a. Object Annotation Pipeline) */

                                /*
                                * Get all accepted BBs without staff vote
                                * Group accepted BBs and count occurances
                                */
                                WITH bb_but_staff_accepted AS
                                (
                                    SELECT COUNT(1) AS total_count,
                                        ibb_accepted.boundingbox_id AS group_column
                                    FROM images_boundingbox_accepted_by AS ibb_accepted
                                    INNER JOIN images_annotator AS ia
                                        ON ibb_accepted.annotator_id = ia.id
                                    INNER JOIN users_user AS uu
                                        ON ia.human_id = uu.id
                                        WHERE NOT uu.is_staff
                                    GROUP BY group_column
                                ),
                                /*
                                * Get all rejected BBs without staff vote
                                * Group rejected BBs and count occurances
                                */
                                bb_but_staff_rejected AS
                                (
                                    SELECT COUNT(1) AS total_count,
                                            ibb_rejected.boundingbox_id AS group_column
                                    FROM images_boundingbox_rejected_by AS ibb_rejected
                                    INNER JOIN images_annotator AS ia
                                        ON ibb_rejected.annotator_id = ia.id
                                    INNER JOIN users_user AS uu
                                        ON ia.human_id = uu.id
                                        WHERE NOT uu.is_staff
                                    GROUP BY group_column

                                ),
                                /*
                                * Get uncertain BBs, this is the target.
                                * Perform a set operation with accepted and rejected grouped BBs.
                                * BBs between -1 and 1 (accepted - rejected votes) are uncertain.
                                */
                                bb_uncertain AS
                                (
                                    SELECT bb_but_staff_accepted.group_column AS bb_id,
                                        COALESCE(bb_but_staff_accepted.total_count, 0) -
                                            COALESCE(bb_but_staff_rejected.total_count, 0) AS difference
                                    FROM bb_but_staff_accepted
                                    INNER JOIN bb_but_staff_rejected
                                        ON bb_but_staff_accepted.group_column = bb_but_staff_rejected.group_column
                                    WHERE COALESCE(bb_but_staff_accepted.total_count, 0) -
                                            COALESCE(bb_but_staff_rejected.total_count, 0) < 2
                                        AND COALESCE(bb_but_staff_accepted.total_count, 0) -
                                            COALESCE(bb_but_staff_rejected.total_count, 0) > -2
                                )
                                /*
                                * Get the images.
                                * The order or operations below matters,
                                * to filter from the smallest group to the largest
                                */
                                SELECT DISTINCT images.id,
                                    images.trigger_timestamp AS ts,
                                    image_upload.priority AS priority
                                FROM bb_uncertain
                                LEFT JOIN images_boundingbox AS ib
                                    ON ib.id = bb_uncertain.bb_id
                                LEFT JOIN images_image AS images
                                    ON images.id = ib.image_id
                                INNER JOIN images_upload AS image_upload
                                    ON images.upload_id = image_upload.id
                                ORDER BY priority DESC, ts DESC
                                """
    )
    return imgs