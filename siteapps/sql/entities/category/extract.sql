-- Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
--
-- This source code is licensed under the MIT license found in the
-- LICENSE file in the root directory of this source tree.


/* Return set of BBs Accepted. With or w/o annotator_se() */
CREATE OR REPLACE FUNCTION bb_accepted(is_annotator_se boolean)
RETURNS TABLE (total_count BIGINT, image_id UUID, bb_id UUID, category CHARACTER VARYING) AS
$$
BEGIN
    IF is_annotator_se THEN -- Staff or expert only
        DROP TABLE IF EXISTS temp_tb_bb_accepted;
        CREATE TEMPORARY TABLE temp_tb_bb_accepted AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                ibb.boundingbox_id AS bb_id,
                category.name AS category
            FROM images_boundingbox_accepted_by AS ibb
            INNER JOIN annotator_se() AS ase
                ON ibb.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON ibb.boundingbox_id = bbox.id
            LEFT JOIN images_category AS category
                ON bbox.id = category.bounding_box_id
            GROUP BY bb_id, bbox.image_id, category.name
            -- LIMIT 100
        );
    ELSE -- All but staff or expert
        DROP TABLE IF EXISTS temp_tb_bb_accepted;
        CREATE TEMPORARY TABLE temp_tb_bb_accepted AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                ibb.boundingbox_id AS bb_id,
                category.name AS category
            FROM images_boundingbox_accepted_by AS ibb
            LEFT JOIN annotator_se() AS ase
                ON ibb.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON ibb.boundingbox_id = bbox.id
            LEFT JOIN images_category AS category
                ON bbox.id = category.bounding_box_id
            WHERE ase.id IS NULL
            GROUP BY bb_id, bbox.image_id, category.name
            -- LIMIT 100
        );
    END IF;
    RETURN QUERY
        SELECT temp_tb_bb_accepted.total_count,
                temp_tb_bb_accepted.image_id,
                temp_tb_bb_accepted.bb_id,
                temp_tb_bb_accepted.category
        FROM temp_tb_bb_accepted;
END;
$$ LANGUAGE plpgsql;


-- SELECT * FROM bb_accepted(false)
-- LIMIT 10;



/*
* Return set of BBs Rejected. With or w/o annotator_se()
*/
CREATE OR REPLACE FUNCTION bb_rejected(is_annotator_se boolean)
RETURNS TABLE (total_count BIGINT, image_id UUID, bb_id UUID, category CHARACTER VARYING) AS
$$
BEGIN
    DROP TABLE IF EXISTS temp_tb_bb_rejected;

    IF is_annotator_se THEN -- Staff or expert only
        CREATE TEMPORARY TABLE temp_tb_bb_rejected AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                ibb.boundingbox_id AS bb_id,
                category.name AS category
            FROM images_boundingbox_rejected_by AS ibb
            INNER JOIN annotator_se() AS ase
                ON ibb.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON ibb.boundingbox_id = bbox.id
            LEFT JOIN images_category AS category
                ON bbox.id = category.bounding_box_id
            GROUP BY bb_id, bbox.image_id, category.name
            -- LIMIT 100
        );
    ELSE -- All but staff or expert
        CREATE TEMPORARY TABLE temp_tb_bb_rejected AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                ibb.boundingbox_id AS bb_id,
                category.name AS category
            FROM images_boundingbox_rejected_by AS ibb
            LEFT JOIN annotator_se() AS ase
                ON ibb.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON ibb.boundingbox_id = bbox.id
            LEFT JOIN images_category AS category
                ON bbox.id = category.bounding_box_id
            WHERE ase.id IS NULL
            GROUP BY bb_id, bbox.image_id, category.name
            -- LIMIT 100
        );
    END IF;
    RETURN QUERY
        SELECT temp_tb_bb_rejected.total_count,
                temp_tb_bb_rejected.image_id,
                temp_tb_bb_rejected.bb_id,
                COALESCE(temp_tb_bb_rejected.category, '') AS category
        FROM temp_tb_bb_rejected;
END;
$$ LANGUAGE plpgsql;



-- SELECT * FROM bb_rejected(false)
-- LIMIT 10;
