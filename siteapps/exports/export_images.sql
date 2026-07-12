-- Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
--
-- This source code is licensed under the MIT license found in the
-- LICENSE file in the root directory of this source tree.

WITH
-- Extract annotator details. Add staff/experts vote weights so that one vote from them is enough
annotator AS (
  SELECT
    ia.id,
    uu.is_staff,
    uu.is_expert,
    CASE
      WHEN uu.is_expert OR uu.is_staff THEN 5
      ELSE 1 -- can further disambiguate between normal volunteers and bots if needed
    END vote_weight
  FROM images_annotator ia
  LEFT JOIN users_user uu ON uu.id = ia.human_id
  LEFT JOIN images_bot ib ON ib.id = ia.bot_id
),
-- Extract all the votes for the categories. There will always be one Created vote when the category is first created.
-- We have to add the Accepted votes and subtract the Rejected votes from that to get the final tally.
category_created AS (
  SELECT
    ic.id category_id,
    ic.bounding_box_id,
    ic.name,
    a.vote_weight created_votes
  FROM images_category ic
  LEFT JOIN annotator a ON a.id = ic.created_by_id
),
category_accepted AS (
  SELECT
    icab.category_id,
    SUM(a.vote_weight) accepted_votes
  FROM images_category_accepted_by icab
  LEFT JOIN annotator a ON a.id = icab.annotator_id
  GROUP BY icab.category_id
),
category_rejected AS (
  SELECT
    icrb.category_id,
    SUM(a.vote_weight) rejected_votes
  FROM images_category_rejected_by icrb
  LEFT JOIN annotator a ON a.id = icrb.annotator_id
  GROUP BY icrb.category_id
),
-- For each bounding box in the Category table, pick the highest voted category
correct_category AS (
  SELECT DISTINCT ON (cc.bounding_box_id)   -- PostgreSQL specific command
    cc.bounding_box_id,
    cc.category_id,
    cc.name,
    cc.created_votes + COALESCE(ca.accepted_votes,0) - COALESCE(cr.rejected_votes,0) votes
  FROM category_created cc
  LEFT JOIN category_accepted ca USING (category_id)
  LEFT JOIN category_rejected cr USING (category_id)
  ORDER BY cc.bounding_box_id, votes DESC
),
-- Get species votes (created, accepted, rejected)
species_created AS (
  SELECT
    s.id species_id,
    s.bounding_box_id,
    isn.name,
    a.vote_weight created_votes
  FROM images_species s
  LEFT JOIN images_speciesname isn ON isn.id = s.name_id
  LEFT JOIN annotator a ON a.id = s.created_by_id
),
species_accepted AS (
  SELECT
    isab.species_id,
    SUM(a.vote_weight) accepted_votes
  FROM images_species_accepted_by isab
  LEFT JOIN annotator a ON a.id = isab.annotator_id
  GROUP BY isab.species_id
),
species_rejected AS (
  SELECT
    isrb.species_id,
    SUM(a.vote_weight) rejected_votes
  FROM images_species_rejected_by isrb
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
  ORDER BY sc.bounding_box_id, votes DESC
),
-- Get the image level aggregated counts via bounding boxes to the species data
species_bounding_boxes AS (
    SELECT
      cs.bounding_box_id,
      bb.image_id,
      cs.species_id,
      CASE WHEN cs.votes >=0 THEN cs.name ELSE NULL END AS name,
      cs.votes,
      COUNT(CASE WHEN cs.votes >= 2 THEN 1 END) OVER (PARTITION BY bb.image_id) AS valid_species,
      COUNT(CASE WHEN cs.votes < 2 AND cs.votes >= 0 THEN 1 END) OVER (PARTITION BY bb.image_id) AS uncertain_species
    FROM correct_species cs
    INNER JOIN images_boundingbox bb ON bb.id = cs.bounding_box_id
),
-- Get the bounding boxes while aggregating validity status by image_id
bounding_boxes AS (
    SELECT
      id AS bounding_box_id,
      image_id,
      validity,
      COUNT(CASE WHEN validity = 'VALID' THEN 1 END) OVER (PARTITION BY image_id) AS valid_bbs,
      COUNT(CASE WHEN validity = 'UNCERTAIN'
              OR validity IS NULL THEN 1 END) OVER (PARTITION BY image_id) AS uncertain_bbs,
      COUNT(CASE WHEN validity = 'VALID' OR validity = 'UNCERTAIN'
              OR validity IS NULL THEN 1 END) OVER (PARTITION BY image_id) AS all_detected_bbs
    FROM images_boundingbox
),
-- Export the images with the appended data from the previous queries as well as additional data
images AS (
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
        volunteer.name as volunteer,
        upload.dropbox_folder_path,
        image.social_media_worthy,
        (SELECT COUNT(1)
            FROM images_image_bbox_checked_by AS bbox_checked_by
            WHERE bbox_checked_by.image_id = image.id) AS bbox_checked_by_count,
        bb.all_detected_bbs AS detected_objects,
        bb.valid_bbs,
        bb.uncertain_bbs,
        category.name,
        (SELECT COUNT(1)
            FROM images_image_species_checked_by AS species_checked_by
            WHERE species_checked_by.image_id = image.id) AS species_checked_by_count,
        species.valid_species,
        species.uncertain_species,
        species.name
    FROM images_image AS image
    INNER JOIN bounding_boxes bb ON bb.image_id = image.id
    LEFT JOIN correct_category AS category ON bb.bounding_box_id = category.bounding_box_id
    LEFT JOIN species_bounding_boxes AS species ON bb.bounding_box_id = species.bounding_box_id
    LEFT JOIN images_upload AS upload
        ON image.upload_id = upload.id
    LEFT JOIN locations_camerastation AS camera_station
        ON upload.camera_station_id = camera_station.id
    LEFT JOIN locations_microsite AS microsite
        ON camera_station.micro_site_id = microsite.id
    LEFT JOIN locations_macrosite AS macrosite
        ON microsite.macro_site_id = macrosite.id
    LEFT JOIN users_user AS volunteer
        ON volunteer.id = upload.volunteer_id
    WHERE
      (bb.uncertain_bbs > 0 OR bb.valid_bbs > 0)
)
SELECT * FROM images
