-- Filter lila_export table to only include images that exist in Dropbox
-- Uses the dropbox_file_index table to check if files can be found
--
-- Usage: Run against the database with psql or Django dbshell

-- First, ensure there's an index on content_hash (run once if not exists)
CREATE INDEX IF NOT EXISTS idx_dropbox_file_index_content_hash
    ON dropbox_file_index(content_hash);

-- Create filtered table with only images found in dropbox_file_index
-- Using EXISTS is faster than IN with a subquery
SELECT le.*
INTO lila_export_5
FROM lila_export_4 le
WHERE EXISTS (
    SELECT 1 FROM dropbox_file_index dfi
    WHERE dfi.content_hash = le.dropbox_content_hash
);

-- Create indexes on new table
CREATE INDEX idx_lila_export_5_image_id ON lila_export_5(image_id);
CREATE INDEX idx_lila_export_5_bbox_id ON lila_export_5(bbox_id);
CREATE INDEX idx_lila_export_5_species ON lila_export_5(species_name);
CREATE INDEX idx_lila_export_5_trigger_timestamp ON lila_export_5(trigger_timestamp);

-- Summary statistics
SELECT
    'lila_export_4 (original)' AS table_name,
    COUNT(DISTINCT image_id) AS images,
    COUNT(*) AS bboxes
FROM lila_export_4
UNION ALL
SELECT
    'lila_export_5 (found in Dropbox)' AS table_name,
    COUNT(DISTINCT image_id) AS images,
    COUNT(*) AS bboxes
FROM lila_export_5
UNION ALL
SELECT
    'Removed (not in Dropbox)' AS table_name,
    COUNT(DISTINCT image_id) AS images,
    COUNT(*) AS bboxes
FROM lila_export_4 le
WHERE NOT EXISTS (
    SELECT 1 FROM dropbox_file_index dfi
    WHERE dfi.content_hash = le.dropbox_content_hash
);
