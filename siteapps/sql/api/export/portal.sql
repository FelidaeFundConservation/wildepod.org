


/*
* ESSA É A QUERY QUE DEVE SER USADA PARA EXPORTAR OS DADOS !!! 
*/
CREATE OR REPLACE FUNCTION portal_export(
                macrosite_param CHARACTER VARYING DEFAULT NULL,
                station_id_param CHARACTER VARYING DEFAULT NULL,
                start_date_param TIMESTAMP WITH TIME ZONE DEFAULT NULL,
                end_date_param TIMESTAMP WITH TIME ZONE DEFAULT NULL                
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
                detected_objects BIGINT,
                validated_objects BIGINT,
                uncertain BIGINT,
                category CHARACTER VARYING,
                species_checked_by_count BIGINT,
                validated_species BIGINT,
                uncertain_species BIGINT,
                species  CHARACTER VARYING) AS 
$$
BEGIN
    /* 
    To check rules to drop or use cache.
    This is to avoid caching on different function calls
    with different arguments.
    */
    DROP TABLE IF EXISTS temp_portal_export;
    CREATE TEMP TABLE temp_portal_export AS (
        SELECT  
            fjuvb.image_id AS image_id,
            ie.dropbox_content_hash,
            ie.dropbox_file_name,
            ie.thumbnail_gcloud_path,
            ie.dropbox_file_path,
            ie.trigger_timestamp,
            ie.latitude,
            ie.longitude,
            ie.is_video, 
            ie.station_id,
            ie.microsite,
            ie.macrosite,
            ie.date_retrieved, 
            ie.volunteer,
            ie.dropbox_folder_path,
            ie.social_media_worthy, 
            ie.bbox_checked_by_count,
            GREATEST(fjuvb.validated_objects, fjuvb.uncertain) AS detected_objects,
            fjuvb.validated_objects,
            fjuvb.uncertain,
            fjuvb.category,
            ie.species_checked_by_count,
            fjuvs.validated_objects AS validated_species,
            fjuvs.uncertain AS uncertain_species,  
            fjuvs.species as species
        FROM full_join_validated_and_uncertain_bbs() AS fjuvb
        INNER JOIN image_enriched(macrosite_param := macrosite_param, 
                                    station_id_param := station_id_param,
                                    start_date_param := start_date_param,
                                    end_date_param := end_date_param) AS ie
            USING(image_id)
        LEFT JOIN full_join_validated_and_uncertain_species() AS fjuvs
            USING(image_id)
        
    );

    RETURN QUERY 
        SELECT *
        FROM temp_portal_export;
END;
$$ LANGUAGE plpgsql;


SELECT * 
FROM portal_export(macrosite_param := 'Point Reyes National Seashore',
                    station_id_param := 'PRS03B')

SELECT count(*)
FROM portal_export(macrosite_param := 'SFPUC')

SELECT count(*) 
FROM portal_export(macrosite_param := 'Point Reyes National Seashore')




ALTER FUNCTION portal_export(
                macrosite_param CHARACTER VARYING,
                station_id_param CHARACTER VARYING
            ) 
VOLATILE;