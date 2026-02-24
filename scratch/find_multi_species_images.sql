-- Find images with more than one species
-- Shows image details and all species found in each multi-species image

WITH multi_species_images AS (
  SELECT
    image_id,
    COUNT(DISTINCT species_name) as species_count,
    array_agg(DISTINCT species_name ORDER BY species_name) as species_list,
    array_agg(DISTINCT species_votes ORDER BY species_name) as species_votes_list
  FROM lila_export
  GROUP BY image_id
  HAVING COUNT(DISTINCT species_name) > 1
)

SELECT
  msi.image_id,
  msi.species_count,
  msi.species_list,
  msi.species_votes_list,
  le.dropbox_file_path,
  le.trigger_timestamp,
  le.dropbox_folder_path
FROM multi_species_images msi
INNER JOIN lila_export le ON le.image_id = msi.image_id
GROUP BY
  msi.image_id,
  msi.species_count,
  msi.species_list,
  msi.species_votes_list,
  le.dropbox_file_path,
  le.trigger_timestamp,
  le.dropbox_folder_path
ORDER BY msi.species_count DESC, le.trigger_timestamp DESC;
