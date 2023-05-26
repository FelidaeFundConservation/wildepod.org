
/* Return set of species Uncertain/Valid/Invalid. Difference of votes rule. */
CREATE OR REPLACE FUNCTION uncertain_valid_invalid_species(uncertain_valid_invalid TEXT) 
RETURNS TABLE (image_id UUID, bb_id UUID, total_accepted BIGINT,
                total_rejected BIGINT, difference BIGINT,
                species CHARACTER VARYING) AS 
$$
BEGIN
    /* Temp table with accepted, rejected and difference */
    DROP TABLE IF EXISTS temp_tb_uncertain_valid_invalid_species;
    DROP TABLE IF EXISTS temp_filter_uncertain_valid_invalid_species;

    CREATE TEMPORARY TABLE temp_tb_uncertain_valid_invalid_species AS (
        SELECT COALESCE(t1.image_id, t2.image_id) AS image_id,
                COALESCE(t1.bb_id, t2.bb_id) AS bb_id,
                COALESCE(t1.total_count,0) AS total_accepted, 
                COALESCE(t2.total_count,0) AS total_rejected, 
                COALESCE(t1.total_count,0) - COALESCE(t2.total_count,0) AS difference,
                COALESCE(t2.species, t1.species) AS species 
        FROM species_accepted(false) AS t1
        FULL JOIN species_rejected(false) AS t2 
            ON t1.bb_id = t2.bb_id
    );
    /* Temp table filter selected by accepted (valid), rejected (invalid) and uncertain */    
    CREATE TEMPORARY TABLE temp_filter_uncertain_valid_invalid_species AS (
            SELECT temp_tuvib.image_id as image_id,
                    temp_tuvib.bb_id as bb_id,
                    temp_tuvib.difference as difference,
                    temp_tuvib.total_accepted as total_accepted,
                    temp_tuvib.total_rejected as total_rejected,
                    temp_tuvib.species
            FROM temp_tb_uncertain_valid_invalid_species AS temp_tuvib
            WHERE
                CASE uncertain_valid_invalid
                    WHEN 'uncertain' THEN temp_tuvib.difference < 2 AND temp_tuvib.difference > -2
                    WHEN 'valid' THEN temp_tuvib.difference >= 2
                    WHEN 'invalid' THEN temp_tuvib.difference <= -2
                END
    );
    RETURN QUERY 
        SELECT temp_filter_uncertain_valid_invalid_species.image_id, 
               temp_filter_uncertain_valid_invalid_species.bb_id, 
               temp_filter_uncertain_valid_invalid_species.total_accepted, 
               temp_filter_uncertain_valid_invalid_species.total_rejected, 
               temp_filter_uncertain_valid_invalid_species.difference,
               temp_filter_uncertain_valid_invalid_species.species
        FROM temp_filter_uncertain_valid_invalid_species;
END;
$$ LANGUAGE plpgsql;


-- SELECT *
-- FROM uncertain_valid_invalid_species('uncertain')
-- LIMIT 10;

/* 
* UNION BBs Accepted by staff or expert rule
* and rule of difference - Not staff/expert rule
SELECT COUNT(*) FROM species_accepted(true)
SELECT COUNT(*) FROM uncertain_valid_invalid_species('valid')
*/
CREATE OR REPLACE FUNCTION all_accepted_species() 
RETURNS TABLE (image_id UUID, bb_id UUID,
                species CHARACTER VARYING) AS 
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_all_accepted_species AS (
        SELECT sa.image_id, sa.bb_id, sa.species
        FROM species_accepted(true) AS sa
        UNION
        SELECT uvis.image_id, uvis.bb_id, uvis.species
        FROM uncertain_valid_invalid_species('valid') AS uvis
    );
    RETURN QUERY 
        SELECT taas.image_id, taas.bb_id, taas.species
        FROM tb_all_accepted_species AS taas;

END;
$$ LANGUAGE plpgsql;


-- SELECT *
-- FROM all_accepted_species()
-- LIMIT 10;



/* GROUP images by accepted bbs */
CREATE OR REPLACE FUNCTION group_images_by_accepted_species() 
RETURNS TABLE (image_id UUID, validated_objects BIGINT,
                species CHARACTER VARYING, bb_id UUID) AS 
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_group_images_by_accepted_species AS (
        SELECT aabb.image_id, 
               COUNT(*) AS validated_objects,
               aabb.species,
               aabb.bb_id

        FROM all_accepted_species() AS aabb
        GROUP BY aabb.image_id, aabb.species, aabb.bb_id
    );
    RETURN QUERY 
        SELECT tgbib.image_id, tgbib.validated_objects, tgbib.species, tgbib.bb_id
        FROM tb_group_images_by_accepted_species AS tgbib;
END;
$$ LANGUAGE plpgsql;

-- SELECT *
-- FROM group_images_by_accepted_species()
-- LIMIT 10;



/* JOIN validated and uncertain BBs of images */
/* species name dont work when join species and category. dont know why... */
CREATE OR REPLACE FUNCTION full_join_validated_and_uncertain_species() 
RETURNS TABLE (image_id UUID, validated_objects BIGINT, 
                uncertain BIGINT, species CHARACTER VARYING) AS 
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS tb_full_join_validated_and_uncertain_species AS (
        SELECT COALESCE(giba.image_id, uvib.image_id) AS image_id, 
                COALESCE(MAX(giba.validated_objects), 0) AS validated_objects,
                COUNT(CASE 
                        WHEN giba.validated_objects IS NULL 
                        THEN 1 END) AS uncertain,
                COALESCE(giba.species, uvib.species) AS species,
                COALESCE(giba.bb_id, uvib.bb_id) AS bb_id

        FROM group_images_by_accepted_species() AS giba 
        FULL OUTER JOIN uncertain_valid_invalid_species('uncertain') AS uvib
            ON giba.image_id = uvib.image_id
        GROUP BY COALESCE(giba.image_id, uvib.image_id), 
                    COALESCE(giba.species, uvib.species),
                    COALESCE(giba.bb_id, uvib.bb_id)
            
    );
    RETURN QUERY 
        SELECT tfjvaus.image_id, 
                tfjvaus.validated_objects, 
                tfjvaus.uncertain,
                tfjvaus.species
        FROM tb_full_join_validated_and_uncertain_species AS tfjvaus;
END;
$$ LANGUAGE plpgsql;


-- SELECT *
-- FROM full_join_validated_and_uncertain_species()
-- -- ORDER BY bb_id
-- LIMIT 10;