

/* 
* This function returns images enriched with all "static"
* information (everything but non annotation).
* Annotation information will be joined on image_id field.
*/
CREATE OR REPLACE FUNCTION image_enriched(macrosite_param CHARACTER VARYING DEFAULT NULL,
                station_id_param CHARACTER VARYING DEFAULT NULL
                ) 
RETURNS TABLE (image_id UUID,
                dropbox_content_hash CHARACTER VARYING, 
                dropbox_file_name TEXT,
                thumbnail_gcloud_path CHARACTER VARYING, 
                dropbox_file_path TEXT,
                trigger_timestamp TIMESTAMP WITH TIME ZONE, 
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                is_video BOOLEAN,
                station_id CHARACTER VARYING,
                microsite CHARACTER VARYING,
                macrosite CHARACTER VARYING,
                date_retrieved TIMESTAMP WITH TIME ZONE, 
                volunteer CHARACTER VARYING,
                dropbox_folder_path TEXT,
                social_media_worthy INTEGER,
                bbox_checked_by_count BIGINT,
                -- category CHARACTER VARYING
                species_checked_by_count BIGINT
                -- species CHARACTER VARYING
                ) AS 
$$
BEGIN
    CREATE TEMPORARY TABLE temp_image_enriched AS (
        SELECT  
            image.id AS image_id,
            image.dropbox_content_hash,
            image.dropbox_file_name,
            image.thumbnail_gcloud_path,
            image.dropbox_file_path,
            image.trigger_timestamp,
            image.latitude,
            image.longitude,
            image.is_video,
            camera_station.station_id,
            microsite.name AS microsite,
            macrosite.name AS macrosite,
            upload.date_retrieved,
            userr.name as volunteer,
            upload.dropbox_folder_path,
            image.social_media_worthy, 
            (SELECT COUNT(1) 
                FROM images_image_bbox_checked_by AS bbox_checked_by
                WHERE bbox_checked_by.image_id = image.id) AS bbox_checked_by_count,
            -- category.name AS category
            (SELECT COUNT(1) 
                FROM images_image_species_checked_by AS species_checked_by
                WHERE species_checked_by.image_id = image.id) AS species_checked_by_count
            --     /*            
            --     "detected_objects",
            --     "validated_objects",
            --     "uncertain_objects",
            --     "objects",

            --     "validated_species",
            --     "uncertain_species",
            --     "species",
            --     */
            
            -- COALESCE(species_name.name, '') AS species
            

        FROM images_image AS image 
        LEFT JOIN images_upload AS upload
            ON image.upload_id = upload.id
        LEFT JOIN locations_camerastation AS camera_station
            ON upload.camera_station_id = camera_station.id
        LEFT JOIN locations_microsite AS microsite
            ON camera_station.micro_site_id = microsite.id
        LEFT JOIN locations_macrosite AS macrosite
            ON microsite.macro_site_id = macrosite.id
        LEFT JOIN users_user AS userr
            ON userr.id = upload.volunteer_id    
        -- LEFT JOIN images_boundingbox AS bbox
        --     ON image.id = bbox.image_id
        -- LEFT JOIN images_category AS category
        --     ON bbox.id = category.bounding_box_id
        -- LEFT JOIN images_species AS species
        --     ON bbox.id = species.bounding_box_id
        -- LEFT JOIN images_speciesname AS species_name
        --     ON species.name_id = species_name.id

        WHERE macrosite_param IS NULL OR macrosite.name = macrosite_param
            AND station_id_param IS NULL OR camera_station.station_id = station_id_param
        -- LIMIT 100
    );

    RETURN QUERY 
        SELECT *
        FROM temp_image_enriched;
END;
$$ LANGUAGE plpgsql;


select * from image_enriched()
where image_id = '000009e8-4835-4819-a75f-bce609d85d51'


-- SELECT * from images_image
-- WHERE id = '9a2494f3-4b3c-4553-915a-d07cd70d2ae7'