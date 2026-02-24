-- LILA Export Query
-- This query is parameterized with start_date and end_date
-- Used by the export_lila Django management command

WITH
-- FILTER FIRST: Get only the images that match our criteria
filtered_images AS (
  SELECT id
  FROM images_image
  WHERE has_wild_animals
    AND species_pipeline_complete
    AND trigger_timestamp >= %(start_date)s
    AND trigger_timestamp <= %(end_date)s
),
-- Get only bounding boxes for filtered images
filtered_bboxes AS (
  SELECT bb.id AS bounding_box_id
  FROM images_boundingbox bb
  INNER JOIN filtered_images fi ON bb.image_id = fi.id
),
-- Extract annotator details (simple - only 295 rows, no need to filter)
annotator AS (
  SELECT
    ia.id,
    CASE
      WHEN COALESCE(uu.is_expert, FALSE) OR COALESCE(uu.is_staff, FALSE) THEN 5
      ELSE 1
    END vote_weight
  FROM images_annotator ia
  LEFT JOIN users_user uu ON uu.id = ia.human_id
),
-- Category processing
category_created AS (
  SELECT
    ic.id category_id,
    ic.bounding_box_id,
    ic.name,
    COALESCE(a.vote_weight, 1) created_votes
  FROM filtered_bboxes fb
  INNER JOIN images_category ic ON ic.bounding_box_id = fb.bounding_box_id
  LEFT JOIN annotator a ON a.id = ic.created_by_id
),
category_accepted AS (
  SELECT
    icab.category_id,
    SUM(COALESCE(a.vote_weight, 1)) accepted_votes
  FROM images_category_accepted_by icab
  INNER JOIN category_created cc ON icab.category_id = cc.category_id
  LEFT JOIN annotator a ON a.id = icab.annotator_id
  GROUP BY icab.category_id
),
category_rejected AS (
  SELECT
    icrb.category_id,
    SUM(COALESCE(a.vote_weight, 1)) rejected_votes
  FROM images_category_rejected_by icrb
  INNER JOIN category_created cc ON icrb.category_id = cc.category_id
  LEFT JOIN annotator a ON a.id = icrb.annotator_id
  GROUP BY icrb.category_id
),
-- Pick highest voted category per bounding box
correct_category AS (
  SELECT DISTINCT ON (cc.bounding_box_id)
    cc.bounding_box_id,
    cc.category_id,
    cc.name,
    cc.created_votes + COALESCE(ca.accepted_votes,0) - COALESCE(cr.rejected_votes,0) votes
  FROM category_created cc
  LEFT JOIN category_accepted ca USING (category_id)
  LEFT JOIN category_rejected cr USING (category_id)
  ORDER BY cc.bounding_box_id, votes DESC
),
-- Species processing
species_created AS (
  SELECT
    s.id species_id,
    s.bounding_box_id,
    isn.name,
    COALESCE(a.vote_weight, 1) created_votes
  FROM filtered_bboxes fb
  INNER JOIN images_species s ON s.bounding_box_id = fb.bounding_box_id
  LEFT JOIN images_speciesname isn ON isn.id = s.name_id
  LEFT JOIN annotator a ON a.id = s.created_by_id
),
species_accepted AS (
  SELECT
    isab.species_id,
    SUM(COALESCE(a.vote_weight, 1)) accepted_votes
  FROM images_species_accepted_by isab
  INNER JOIN species_created sc ON isab.species_id = sc.species_id
  LEFT JOIN annotator a ON a.id = isab.annotator_id
  GROUP BY isab.species_id
),
species_rejected AS (
  SELECT
    isrb.species_id,
    SUM(COALESCE(a.vote_weight, 1)) rejected_votes
  FROM images_species_rejected_by isrb
  INNER JOIN species_created sc ON isrb.species_id = sc.species_id
  LEFT JOIN annotator a ON a.id = isrb.annotator_id
  GROUP BY isrb.species_id
),
-- Pick highest voted species per bounding box
correct_species AS (
  SELECT DISTINCT ON (sc.bounding_box_id)
    sc.bounding_box_id,
    sc.species_id,
    sc.name,
    sc.created_votes + COALESCE(sa.accepted_votes,0) - COALESCE(sr.rejected_votes,0) votes
  FROM species_created sc
  LEFT JOIN species_accepted sa USING (species_id)
  LEFT JOIN species_rejected sr USING (species_id)
  ORDER BY sc.bounding_box_id, votes desc
)
-- Final result
SELECT
    image.id AS image_id,
    bb.id AS bbox_id,
    image.dropbox_content_hash,
    image.dropbox_file_name,
    image.thumbnail_gcloud_path,
    image.dropbox_file_path,
    image.trigger_timestamp,
    upload.dropbox_folder_path,
    category.name AS category_name,
    category.votes AS category_votes,
    species.name AS species_name,
    species.votes AS species_votes
FROM images_image AS image
INNER JOIN filtered_images fi ON image.id = fi.id
INNER JOIN images_boundingbox bb ON bb.image_id = image.id
INNER JOIN correct_category AS category ON bb.id = category.bounding_box_id
INNER JOIN correct_species AS species ON bb.id = species.bounding_box_id
LEFT JOIN images_upload AS upload ON image.upload_id = upload.id
WHERE category.votes >= 2
  AND species.votes >= 2;
