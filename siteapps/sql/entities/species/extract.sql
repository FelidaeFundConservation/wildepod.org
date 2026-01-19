


/* Return set of species_accepted. With or w/o annotator_se() */
CREATE OR REPLACE FUNCTION species_accepted(is_annotator_se boolean)
RETURNS TABLE (total_count BIGINT, image_id UUID, bb_id UUID, species CHARACTER VARYING) AS
$$
BEGIN
    IF is_annotator_se THEN -- Staff or expert only
        DROP TABLE IF EXISTS temp_tb_species_accepted;
        CREATE TEMPORARY TABLE temp_tb_species_accepted AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                bbox.id AS bb_id,
                species_name.name AS species
            FROM images_species AS isp
            INNER JOIN images_species_accepted_by AS isab
                ON isp.id = isab.species_id
            INNER JOIN annotator_se() AS ase
                ON isab.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON isp.bounding_box_id = bbox.id
            LEFT JOIN images_species AS species
                ON bbox.id = species.bounding_box_id
            LEFT JOIN images_speciesname AS species_name
                ON species.name_id = species_name.id
            GROUP BY bb_id, bbox.image_id, species_name.name
            -- LIMIT 100
        );
    ELSE -- All but staff or expert
        DROP TABLE IF EXISTS temp_tb_species_accepted;
        CREATE TEMPORARY TABLE temp_tb_species_accepted AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                bbox.id AS bb_id,
                species_name.name AS species
            FROM images_species AS isp
            INNER JOIN images_species_accepted_by AS isab
                ON isp.id = isab.species_id
            LEFT JOIN annotator_se() AS ase
                ON isab.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON isp.bounding_box_id = bbox.id
            LEFT JOIN images_species AS species
                ON bbox.id = species.bounding_box_id
            LEFT JOIN images_speciesname AS species_name
                ON species.name_id = species_name.id
            WHERE ase.id IS NULL
            GROUP BY bb_id, bbox.image_id, species_name.name
        );
    END IF;
    RETURN QUERY
        SELECT temp_tb_species_accepted.total_count,
                temp_tb_species_accepted.image_id,
                temp_tb_species_accepted.bb_id,
                temp_tb_species_accepted.species
        FROM temp_tb_species_accepted;
END;
$$ LANGUAGE plpgsql;

-- SELECT * FROM species_accepted(true)
-- LIMIT 100;



/*
* Return set of species_rejected. With or w/o annotator_se()
*/
CREATE OR REPLACE FUNCTION species_rejected(is_annotator_se boolean)
RETURNS TABLE (total_count BIGINT, image_id UUID, bb_id UUID, species CHARACTER VARYING) AS
$$
BEGIN
    DROP TABLE IF EXISTS temp_tb_species_rejected;

    IF is_annotator_se THEN -- Staff or expert only
        CREATE TEMPORARY TABLE temp_tb_species_rejected AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                bbox.id AS bb_id,
                species_name.name AS species
            FROM images_species AS isp
            INNER JOIN images_species_rejected_by AS isab
                ON isp.id = isab.species_id
            INNER JOIN annotator_se() AS ase
                ON isab.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON isp.bounding_box_id = bbox.id
            LEFT JOIN images_species AS species
                ON bbox.id = species.bounding_box_id
            LEFT JOIN images_speciesname AS species_name
                ON species.name_id = species_name.id
            GROUP BY bb_id, bbox.image_id, species_name.name
        );
    ELSE -- All but staff or expert
        CREATE TEMPORARY TABLE temp_tb_species_rejected AS (
            SELECT COUNT(1) AS total_count,
                bbox.image_id AS image_id,
                bbox.id AS bb_id,
                species_name.name AS species
            FROM images_species AS isp
            INNER JOIN images_species_rejected_by AS isab
                ON isp.id = isab.species_id
            LEFT JOIN annotator_se() AS ase
                ON isab.annotator_id = ase.id
            LEFT JOIN images_boundingbox AS bbox
                ON isp.bounding_box_id = bbox.id
            LEFT JOIN images_species AS species
                ON bbox.id = species.bounding_box_id
            LEFT JOIN images_speciesname AS species_name
                ON species.name_id = species_name.id
            WHERE ase.id IS NULL
            GROUP BY bb_id, bbox.image_id, species_name.name
        );
    END IF;
    RETURN QUERY
        SELECT temp_tb_species_rejected.total_count,
                temp_tb_species_rejected.image_id,
                temp_tb_species_rejected.bb_id,
                temp_tb_species_rejected.species
        FROM temp_tb_species_rejected;
END;
$$ LANGUAGE plpgsql;



-- SELECT * FROM species_rejected(true)
-- LIMIT 100;
