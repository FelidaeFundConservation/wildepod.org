-- Create table with images that have NO rejections on any bounding box
-- (no category rejections AND no species rejections)
--
-- Usage: Run against the database with psql or Django dbshell
--   psql -d wildepod -f scratch/filter_no_rejections.sql

WITH images_with_category_rejections AS (
    -- Find image_ids where ANY bbox has a category rejection
    SELECT DISTINCT le.image_id
    FROM lila_export_3 le
    INNER JOIN images_category ic ON ic.bounding_box_id = le.bbox_id
    INNER JOIN images_category_rejected_by icrb ON icrb.category_id = ic.id
),
images_with_species_rejections AS (
    -- Find image_ids where ANY bbox has a species rejection
    SELECT DISTINCT le.image_id
    FROM lila_export_3 le
    INNER JOIN images_species isp ON isp.bounding_box_id = le.bbox_id
    INNER JOIN images_species_rejected_by isrb ON isrb.species_id = isp.id
)
-- Select rows for images with NO rejections of either type
SELECT le.*
INTO lila_export_no_rejections
FROM lila_export_3 le
WHERE le.image_id NOT IN (SELECT image_id FROM images_with_category_rejections)
  AND le.image_id NOT IN (SELECT image_id FROM images_with_species_rejections);

-- Create indexes
CREATE INDEX idx_lila_export_no_rejections_image_id ON lila_export_no_rejections(image_id);
CREATE INDEX idx_lila_export_no_rejections_bbox_id ON lila_export_no_rejections(bbox_id);
CREATE INDEX idx_lila_export_no_rejections_species ON lila_export_no_rejections(species_name);

-- Summary
SELECT
    'Original' AS table_name,
    COUNT(DISTINCT image_id) AS images,
    COUNT(*) AS bboxes
FROM lila_export_3
UNION ALL
SELECT
    'No rejections' AS table_name,
    COUNT(DISTINCT image_id) AS images,
    COUNT(*) AS bboxes
FROM lila_export_no_rejections;
