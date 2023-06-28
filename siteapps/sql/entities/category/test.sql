





SELECT * 
FROM bb_accepted(true)
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'

SELECT * 
FROM bb_accepted(false)
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'

SELECT * 
FROM all_accepted_bbs()
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'

SELECT * 
FROM group_images_by_accepted_bbs()
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'

SELECT * 
FROM full_join_validated_and_uncertain_bbs()
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'


SELECT * 
FROM uncertain_valid_invalid_bbs('uncertain') 
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'




SELECT * 
FROM uncertain_valid_invalid_bbs('uncertain') 
-- LIMIT 10;
WHERE image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'



SELECT COALESCE(t1.image_id, t2.image_id) AS image_id,
        COALESCE(t1.bb_id, t2.bb_id) AS bb_id,
        COALESCE(t1.total_count,0) AS total_accepted, 
        COALESCE(t2.total_count,0) AS total_rejected, 
        COALESCE(t1.total_count,0) - COALESCE(t2.total_count,0) AS difference
FROM bb_accepted(false) AS t1
FULL JOIN bb_rejected(false) AS t2 
    ON t1.bb_id = t2.bb_id
WHERE t1.image_id = '2dd456e5-e371-4861-8a8e-e82e26c8f88b'


-- SELECT * 
-- FROM uncertain_valid_invalid_bbs('uncertain')
-- LIMIT 10;



