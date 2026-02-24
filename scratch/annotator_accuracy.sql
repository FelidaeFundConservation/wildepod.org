-- Annotator Accuracy Queries
-- Compare human annotator votes against final consensus in lila_export_5
-- lila_export_5 contains clean wild animal labels with species_votes >= 2

-- =============================================================================
-- Query 1: Agreement rate for species annotations - Normal vs Staff/Expert users
-- =============================================================================
WITH user_votes AS (
    -- Get all species annotations (created + accepted) with user type
    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type,
        'created' AS vote_type
    FROM images_species s
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON s.created_by_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'

    UNION ALL

    -- Accepted votes (user agreed with a species annotation)
    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type,
        'accepted' AS vote_type
    FROM images_species_accepted_by sab
    JOIN images_species s ON sab.species_id = s.id
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON sab.annotator_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'
)
SELECT
    uv.user_type,
    COUNT(*) AS total_votes,
    SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) AS correct_votes,
    ROUND(100.0 * SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) / COUNT(*), 2) AS agreement_pct
FROM user_votes uv
JOIN lila_export_5 le ON uv.bounding_box_id = le.bbox_id
GROUP BY uv.user_type
ORDER BY user_type;


-- =============================================================================
-- Query 2: Breakdown by vote type (created vs accepted)
-- =============================================================================
WITH user_votes AS (
    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type,
        'created' AS vote_type
    FROM images_species s
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON s.created_by_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'

    UNION ALL

    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type,
        'accepted' AS vote_type
    FROM images_species_accepted_by sab
    JOIN images_species s ON sab.species_id = s.id
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON sab.annotator_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'
)
SELECT
    uv.user_type,
    uv.vote_type,
    COUNT(*) AS total_votes,
    SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) AS correct_votes,
    ROUND(100.0 * SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) / COUNT(*), 2) AS agreement_pct
FROM user_votes uv
JOIN lila_export_5 le ON uv.bounding_box_id = le.bbox_id
GROUP BY uv.user_type, uv.vote_type
ORDER BY uv.user_type, uv.vote_type;


-- =============================================================================
-- Query 3: Per-annotator accuracy (top 20 most active)
-- =============================================================================
WITH user_votes AS (
    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        u.name AS annotator_name,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type
    FROM images_species s
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON s.created_by_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'

    UNION ALL

    SELECT
        s.bounding_box_id,
        sn.name AS voted_species,
        a.id AS annotator_id,
        u.name AS annotator_name,
        CASE
            WHEN u.is_staff OR u.is_expert THEN 'staff_expert'
            ELSE 'normal'
        END AS user_type
    FROM images_species_accepted_by sab
    JOIN images_species s ON sab.species_id = s.id
    JOIN images_speciesname sn ON s.name_id = sn.id
    JOIN images_annotator a ON sab.annotator_id = a.id
    JOIN users_user u ON a.human_id = u.id
    WHERE a.type = 'human'
)
SELECT
    uv.annotator_name,
    uv.user_type,
    COUNT(*) AS total_votes,
    SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) AS correct_votes,
    ROUND(100.0 * SUM(CASE WHEN uv.voted_species = le.species_name THEN 1 ELSE 0 END) / COUNT(*), 2) AS agreement_pct
FROM user_votes uv
JOIN lila_export_5 le ON uv.bounding_box_id = le.bbox_id
GROUP BY uv.annotator_id, uv.annotator_name, uv.user_type
HAVING COUNT(*) >= 100  -- Only annotators with 100+ votes
ORDER BY total_votes DESC
LIMIT 20;
