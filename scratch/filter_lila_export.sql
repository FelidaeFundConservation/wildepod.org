-- Filter LILA export to remove images containing human-related species
-- Creates a new table with only wildlife images

-- Species to exclude (if ANY bbox in an image has these, remove the ENTIRE image)
WITH excluded_species AS (
  SELECT UNNEST(ARRAY[
    'Motorized vehicle',
    'Human',
    'Non motorized vehicle (bike)',
    'Horse rider',
    'Electric Bicycle',
    'Cyclist'
  ]) AS species_name
),
-- Find all image_ids that contain at least one excluded species
images_to_exclude AS (
  SELECT DISTINCT le.image_id
  FROM lila_export_2 le
  INNER JOIN excluded_species es ON le.species_name = es.species_name
)
-- Create new table with only clean wildlife images
SELECT le.*
INTO lila_export_3
FROM lila_export_2 le
WHERE le.image_id NOT IN (SELECT image_id FROM images_to_exclude);

-- Create indexes on new table
CREATE INDEX idx_lila_export_3_image_id ON lila_export_3(image_id);
CREATE INDEX idx_lila_export_3_bbox_id ON lila_export_3(bbox_id);
CREATE INDEX idx_lila_export_3_trigger_timestamp ON lila_export_3(trigger_timestamp);
CREATE INDEX idx_lila_export_3_species ON lila_export_3(species_name);

-- Summary statistics
WITH excluded_species AS (
  SELECT UNNEST(ARRAY[
    'Motorized vehicle',
    'Human',
    'Non motorized vehicle (bike)',
    'Horse rider',
    'Electric Bicycle',
    'Cyclist'
  ]) AS species_name
),
images_to_exclude AS (
  SELECT DISTINCT le.image_id
  FROM lila_export_2 le
  INNER JOIN excluded_species es ON le.species_name = es.species_name
)
SELECT
  'Original table' AS table_name,
  COUNT(DISTINCT image_id) AS unique_images,
  COUNT(*) AS total_bboxes
FROM lila_export_2
UNION ALL
SELECT
  'Filtered table' AS table_name,
  COUNT(DISTINCT image_id) AS unique_images,
  COUNT(*) AS total_bboxes
FROM lila_export_3
UNION ALL
SELECT
  'Excluded images' AS table_name,
  COUNT(DISTINCT image_id) AS unique_images,
  COUNT(*) AS total_bboxes
FROM lila_export_2
WHERE image_id IN (SELECT image_id FROM images_to_exclude);
