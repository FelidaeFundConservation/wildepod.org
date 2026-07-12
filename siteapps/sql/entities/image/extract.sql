-- Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
--
-- This source code is licensed under the MIT license found in the
-- LICENSE file in the root directory of this source tree.

/*
* This function returns images enriched with all "static"
* information (everything but non annotation).
* Annotation information will be joined on image_id field.
*/
CREATE OR REPLACE FUNCTION image_enriched(
                macrosite_param CHARACTER VARYING DEFAULT NULL,
                station_id_param CHARACTER VARYING DEFAULT NULL,
                start_date_param TIMESTAMPTZ DEFAULT NULL,
                end_date_param TIMESTAMPTZ DEFAULT NULL
                )
RETURNS TABLE (
                image_id UUID,
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
                species_checked_by_count BIGINT
                ) AS
$$
BEGIN
    /*
    To check rules to drop or use cache.
    This is to avoid caching on different function calls
    with different arguments.
    */
    DROP TABLE IF EXISTS temp_image_enriched;
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
            (SELECT COUNT(1)
                FROM images_image_species_checked_by AS species_checked_by
                WHERE species_checked_by.image_id = image.id) AS species_checked_by_count

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

        WHERE (macrosite_param IS NULL OR macrosite.name = macrosite_param)
          AND (station_id_param IS NULL OR camera_station.station_id = station_id_param)
          AND (start_date_param IS NULL OR image.trigger_timestamp >= start_date_param)
          AND (end_date_param IS NULL OR image.trigger_timestamp <= end_date_param)
    );

    RETURN QUERY
        SELECT *
        FROM temp_image_enriched;
END;
$$ LANGUAGE plpgsql;


-- SELECT * from image_enriched(start_date_param := '2020-01-01')
-- WHERE image_id = '000009e8-4835-4819-a75f-bce609d85d51'
-- AND trigger_timestamp >= '2021-01-01'


-- SELECT * from images_image
-- WHERE id = '9a2494f3-4b3c-4553-915a-d07cd70d2ae7'
