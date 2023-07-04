/*
Get the bounding boxes for a given image, and if accepted or rejected.
*/
CREATE OR REPLACE FUNCTION image_bbs(image_id_param UUID) 
RETURNS TABLE (image_id UUID, bb_id UUID, total_accepted BIGINT,
                         total_rejected BIGINT) AS 
$$
BEGIN
    RETURN QUERY
        SELECT image.id as image_id, 
                ibb.id as bb_id,
                COUNT(ibb_accepted_by.id) AS total_accepted,
                CAST(0 AS BIGINT) AS total_rejected
            FROM images_image AS image
            INNER JOIN images_boundingbox AS ibb
                ON image.id = ibb.image_id
            LEFT JOIN images_boundingbox_accepted_by AS ibb_accepted_by
                ON ibb.id = ibb_accepted_by.boundingbox_id
            WHERE image.id = image_id_param                
            GROUP BY image.id, ibb.id
        UNION
        SELECT image.id as image_id, 
                ibb.id as bb_id,
                CAST(0 AS BIGINT) AS total_accepted,
                COUNT(ibb_rejected_by.id) AS total_rejected                 
            FROM images_image AS image
            INNER JOIN images_boundingbox AS ibb
                ON image.id = ibb.image_id
            LEFT JOIN images_boundingbox_rejected_by AS ibb_rejected_by
                ON ibb.id = ibb_rejected_by.boundingbox_id
            WHERE image.id = image_id_param
            GROUP BY image.id, ibb.id
    ;

END;
$$ LANGUAGE plpgsql;