-- Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
--
-- This source code is licensed under the MIT license found in the
-- LICENSE file in the root directory of this source tree.

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
