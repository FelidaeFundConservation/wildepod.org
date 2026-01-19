/* ================================ */
/* Using Basic Functions try to not */
/* access database tables directly  */
/* ================================ */



/* Return set of BBs Uncertain/Valid/Invalid. Difference of votes rule. */
CREATE OR REPLACE FUNCTION uncertain_valid_invalid_bbs(uncertain_valid_invalid TEXT)
RETURNS TABLE (image_id UUID, bb_id UUID, total_accepted BIGINT,
                total_rejected BIGINT, difference BIGINT,
                category CHARACTER VARYING) AS
$$
BEGIN
    /* Temp table with accepted, rejected and difference */
    DROP TABLE IF EXISTS temp_tb_uncertain_valid_invalid_bbs;
    DROP TABLE IF EXISTS temp_filter_uncertain_valid_invalid_bbs;

    CREATE TEMPORARY TABLE temp_tb_uncertain_valid_invalid_bbs AS (
        SELECT COALESCE(t1.image_id, t2.image_id) AS image_id,
                COALESCE(t1.bb_id, t2.bb_id) AS bb_id,
                COALESCE(t1.total_count,0) AS total_accepted,
                COALESCE(t2.total_count,0) AS total_rejected,
                COALESCE(t1.total_count,0) - COALESCE(t2.total_count,0) AS difference,
                COALESCE(t1.category, t2.category) AS category
        FROM bb_accepted(false) AS t1
        FULL JOIN bb_rejected(false) AS t2
            ON t1.bb_id = t2.bb_id
    );
    /* Temp table filter selected by accepted (valid), rejected (invalid) and uncertain */
    CREATE TEMPORARY TABLE temp_filter_uncertain_valid_invalid_bbs AS (
            SELECT temp_tuvib.image_id as image_id,
                    temp_tuvib.bb_id as bb_id,
                    temp_tuvib.difference as difference,
                    temp_tuvib.total_accepted as total_accepted,
                    temp_tuvib.total_rejected as total_rejected,
                    temp_tuvib.category as category
            FROM temp_tb_uncertain_valid_invalid_bbs AS temp_tuvib
            WHERE
                CASE uncertain_valid_invalid
                    WHEN 'uncertain' THEN temp_tuvib.difference < 2 AND temp_tuvib.difference > -2
                    WHEN 'valid' THEN temp_tuvib.difference >= 2
                    WHEN 'invalid' THEN temp_tuvib.difference <= -2
                END
    );
    RETURN QUERY
        SELECT
               temp_filter_uncertain_valid_invalid_bbs.image_id,
               temp_filter_uncertain_valid_invalid_bbs.bb_id,
               temp_filter_uncertain_valid_invalid_bbs.total_accepted,
               temp_filter_uncertain_valid_invalid_bbs.total_rejected,
               temp_filter_uncertain_valid_invalid_bbs.difference,
                temp_filter_uncertain_valid_invalid_bbs.category
        FROM temp_filter_uncertain_valid_invalid_bbs;
END;
$$ LANGUAGE plpgsql;

-- SELECT *
-- FROM uncertain_valid_invalid_bbs('uncertain')
-- LIMIT 10;


/*
* UNION BBs Accepted by staff or expert rule
* and rule of difference - Not staff/expert rule
SELECT COUNT(*) FROM bb_accepted(true)
SELECT COUNT(*) FROM uncertain_valid_invalid_bbs('valid')
*/
CREATE OR REPLACE FUNCTION all_accepted_bbs()
RETURNS TABLE (image_id UUID, bb_id UUID, category CHARACTER VARYING) AS
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_all_accepted_bbs AS (
        SELECT bba.image_id, bba.bb_id , bba.category
        FROM bb_accepted(true) AS bba
        UNION
        SELECT uvib.image_id, uvib.bb_id, uvib.category
        FROM uncertain_valid_invalid_bbs('valid') AS uvib
    );
    RETURN QUERY
        SELECT taab.image_id, taab.bb_id, taab.category
        FROM tb_all_accepted_bbs AS taab;

END;
$$ LANGUAGE plpgsql;

-- SELECT *
-- FROM all_accepted_bbs()
-- LIMIT 10;



/* GROUP images by accepted bbs */
CREATE OR REPLACE FUNCTION group_images_by_accepted_bbs()
RETURNS TABLE (image_id UUID, validated_objects BIGINT,
                category CHARACTER VARYING) AS
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_group_images_by_accepted_bbs AS (
        SELECT aabb.image_id,
               COUNT(*) AS validated_objects,
               aabb.category
        FROM all_accepted_bbs() AS aabb
        GROUP BY aabb.image_id, aabb.category
    );
    RETURN QUERY
        SELECT tgbib.image_id, tgbib.validated_objects, tgbib.category
        FROM tb_group_images_by_accepted_bbs AS tgbib;
END;
$$ LANGUAGE plpgsql;

-- SELECT *
-- FROM group_images_by_accepted_bbs()
-- LIMIT 10;

/* JOIN validated and uncertain BBs of images */
CREATE OR REPLACE FUNCTION full_join_validated_and_uncertain_bbs()
RETURNS TABLE (image_id UUID, validated_objects BIGINT, uncertain BIGINT,
                category CHARACTER VARYING) AS
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_full_join_validated_and_uncertain AS (
        SELECT COALESCE(giba.image_id, uvib.image_id) AS image_id,
                COALESCE(MAX(giba.validated_objects), 0) AS validated_objects,
                COUNT(CASE
                        WHEN giba.validated_objects IS NULL
                        THEN 1 END) AS uncertain,
                COALESCE(giba.category, uvib.category) AS category
        FROM group_images_by_accepted_bbs() AS giba
        FULL OUTER JOIN uncertain_valid_invalid_bbs('uncertain') AS uvib
            ON giba.image_id = uvib.image_id
        GROUP BY COALESCE(giba.image_id, uvib.image_id),
                COALESCE(giba.category, uvib.category)
    );
    RETURN QUERY
        SELECT tfjvau.image_id, tfjvau.validated_objects,
                tfjvau.uncertain, tfjvau.category
        FROM tb_full_join_validated_and_uncertain AS tfjvau;
END;
$$ LANGUAGE plpgsql;

-- SELECT *
-- FROM group_images_by_accepted_bbs()
-- LIMIT 10;
