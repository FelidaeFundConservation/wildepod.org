/* Return set of rows where user is staff or expert */
CREATE OR REPLACE FUNCTION annotator_se() 
RETURNS TABLE (id BIGINT, name character varying) AS 
$$
BEGIN
    CREATE TEMP TABLE if NOT EXISTS temp_table AS (
        SELECT *
        FROM users_user AS uu
        WHERE uu.is_staff
            OR uu.is_expert
    );
    RETURN QUERY 
        SELECT ia.id AS id , tt.name AS name
        FROM temp_table AS tt
        INNER JOIN images_annotator AS ia
            ON ia.human_id = tt.id;

END;
$$ LANGUAGE plpgsql;
