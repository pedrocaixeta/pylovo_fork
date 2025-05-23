CREATE OR REPLACE FUNCTION pylovo_input.classify_building_type(funktion TEXT)
RETURNS TEXT AS $$
BEGIN
    CASE funktion
        -- Residential Buildings
        WHEN '31001_1000' THEN RETURN 'residential'; -- Wohngebäude
        WHEN '31001_2463' THEN RETURN 'residential'; -- Garage
        WHEN '31001_9998' THEN RETURN 'residential'; -- Unspecified

        -- Industrial Buildings
        WHEN '31001_2000' THEN RETURN 'industrial'; -- Gebäude für Wirtschaft oder Gewerbe
        WHEN '31001_2523' THEN RETURN 'industrial'; -- Umformer
        WHEN '31001_2513' THEN RETURN 'industrial'; -- Wasserbehälter

        -- Commercial Buildings, stores and caffes
        WHEN '31001_2072' THEN RETURN 'commercial'; -- Jugendherberge
        WHEN '31001_2461' THEN RETURN 'commercial'; -- Parkhaus
        WHEN '31001_2465' THEN RETURN 'commercial'; -- Tiefgarage
        WHEN '31001_3091' THEN RETURN 'commercial'; -- Bahnhofsgebäude
        WHEN '31001_3290' THEN RETURN 'commercial'; -- Touristisches Informationszentrum

        -- Public Buildings, buildings by governments
        WHEN '31001_3000' THEN RETURN 'public'; -- Gebäude für öffentliche Zwecke
        WHEN '31001_3012' THEN RETURN 'public'; -- Rathaus
        WHEN '31001_3017' THEN RETURN 'public'; -- Kreisverwaltung
        WHEN '31001_3018' THEN RETURN 'public'; -- Bezirksregierung
        WHEN '31001_3020' THEN RETURN 'public'; -- Gebäude für Bildung und Forschung
        WHEN '31001_3031' THEN RETURN 'public'; -- Schloss
        WHEN '31001_3038' THEN RETURN 'public'; -- Burg, Festung
        WHEN '31001_3041' THEN RETURN 'public'; -- Kirche
        WHEN '31001_3042' THEN RETURN 'public'; -- Synagoge
        WHEN '31001_3043' THEN RETURN 'public'; -- Kapelle
        WHEN '31001_3046' THEN RETURN 'public'; -- Moschee
        WHEN '31001_3047' THEN RETURN 'public'; -- Tempel
        WHEN '31001_3048' THEN RETURN 'public'; -- Kloster
        WHEN '31001_3051' THEN RETURN 'public'; -- Krankenhaus
        WHEN '31001_3052' THEN RETURN 'public'; -- Heilanstalt, Pflegeanstalt, Pflegestation
        WHEN '31001_3065' THEN RETURN 'public'; -- Kinderkrippe, Kindergarten, Kindertagesstätte
        WHEN '31001_3071' THEN RETURN 'public'; -- Polizei
        WHEN '31001_3072' THEN RETURN 'public'; -- Feuerwehr
        WHEN '31001_3073' THEN RETURN 'public'; -- Kaserne
        WHEN '31001_3075' THEN RETURN 'public'; -- Justizvollzugsanstalt
        WHEN '31001_3242' THEN RETURN 'public'; -- Sanatorium

        -- Infrastructure or Misc (not classified, so raise error)
        --WHEN '31001_9998' THEN RAISE EXCEPTION 'Unspecified building type: %', funktion;
        WHEN '51007_1500' THEN RAISE EXCEPTION 'Structure (historical wall) is not a building: %', funktion;
        WHEN '51007_1800' THEN RAISE EXCEPTION 'Structure (wall) is not a building: %', funktion;
        WHEN '51009_1610' THEN RAISE EXCEPTION 'Structure (roofing) is not a building: %', funktion;
        WHEN '53001_1800' THEN RAISE EXCEPTION 'Structure (bridge) is not a building: %', funktion;
        WHEN '53009_2030' THEN RAISE EXCEPTION 'Structure (dam) is not a building: %', funktion;
        WHEN '53009_2050' THEN RAISE EXCEPTION 'Structure (weir) is not a building: %', funktion;

        ELSE
            RAISE EXCEPTION 'Unknown building function code: %', funktion;
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;


CREATE TABLE pylovo_input.building (
    id bigint PRIMARY KEY,
    objectid text UNIQUE,
    height double precision,
    floor_area double precision,
    floor_number int,
    building_use text,
    building_use_id text,
    building_type text,
    geom geometry(MultiPolygon, 3035)
);
CREATE INDEX IF NOT EXISTS building_geom_idx ON pylovo_input.building USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_building_type_check ON pylovo_input.building(id, building_type, building_use);

-- fill id, objectid and building use columns
INSERT INTO pylovo_input.building (id, objectid, building_use, building_use_id)
SELECT
    f.id,
    f.objectid,
    pylovo_input.classify_building_type(p.val_string) as building_use,
    p.val_string as building_use_id
FROM feature f
JOIN property p ON f.id = p.feature_id
WHERE
    f.objectclass_id = 901 AND
    p.namespace_id = 10 AND
    p.name = 'function' AND
    p.val_string LIKE '31001_%' AND -- only allow buildings
    p.val_string <> '31001_2463' AND -- exclude garages
    p.val_string <> '31001_2513' -- exclude water containers
ORDER BY f.id;

-- fill height column
WITH height_data AS (
    SELECT p.feature_id, p.val_double
    FROM property p
    WHERE
        p.name = 'value' AND
        p.parent_id IN (SELECT id FROM property WHERE name = 'height')
)
UPDATE pylovo_input.building
SET height = hd.val_double
FROM height_data hd
WHERE id = hd.feature_id;

-- delete buildings below a height threshold
DELETE FROM pylovo_input.building
WHERE height < 3.5;

-- fill geom and floor_area columns
WITH ground_data AS (
    SELECT
        regexp_replace(f.objectid, '_[^_]*-.*$', '') as building_objectid,
        cast(p.val_string as double precision) as area,
        ST_Transform(ST_Force2D(gd.geometry), 3035) as geometry
    FROM feature f
    JOIN geometry_data gd ON f.id = gd.feature_id
    JOIN property p ON gd.feature_id = p.feature_id
    WHERE
        f.objectclass_id = 710 AND  -- GroundSurface
        p.name = 'Flaeche'
)
UPDATE pylovo_input.building
SET floor_area = gd.area, geom = gd.geometry
FROM ground_data gd
WHERE objectid = building_objectid;

-- delete buildings below an area threshold
DELETE FROM pylovo_input.building
WHERE building.floor_area < 15 OR (building.floor_area * height) < 150;

-- fill floor_number column
WITH floor_number_data AS (
    SELECT feature_id, val_int
    FROM property
    WHERE name = 'storeysAboveGround'
)
UPDATE pylovo_input.building
SET floor_number = fnd.val_int
FROM floor_number_data fnd
WHERE id = fnd.feature_id;

-- fill in missing floor_number values
WITH average_floor_height AS (
    SELECT
        building_use_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP ( ORDER BY (height / floor_number) ) as height_per_floor
    FROM pylovo_input.building
    GROUP BY building_use_id
)
UPDATE pylovo_input.building b
SET floor_number = ROUND(height / COALESCE(afh.height_per_floor, height))
FROM average_floor_height afh
WHERE
    b.floor_number IS NULL AND
    b.building_use_id = afh.building_use_id;

-- fill residential_building_type
CREATE MATERIALIZED VIEW pylovo_input.neighbors AS
    SELECT
        a.id AS a_id,
        b.id AS b_id,
        a.floor_area AS a_area,
        b.floor_area AS b_area
    FROM pylovo_input.building a
    JOIN pylovo_input.building b ON
        a.id != b.id AND
        a.building_use = 'residential' AND
        b.building_use = 'residential' AND
        a.geom && b.geom AND  -- check for bbox intersection
        ST_DWithin(a.geom, b.geom, 0.01);

CREATE MATERIALIZED VIEW pylovo_input.neighbor_counts AS
    SELECT a_id as id, count(b_id)
    FROM pylovo_input.neighbors
    GROUP BY a_id;

-- Apartment Buildings (AB):
-- Typically have 4+ floors and many neighbors
-- or if floor area > 1500
UPDATE pylovo_input.building
SET building_type = 'AB'
WHERE building_use = 'residential'
  AND building_type IS NULL
  AND (floor_number >= 4
    OR (
           floor_number >= 3 AND
           EXISTS (SELECT 1
                   FROM pylovo_input.neighbor_counts
                   WHERE pylovo_input.neighbor_counts.id = pylovo_input.building.id
                     AND count >= 3)
           )
    OR floor_area > 1500);

-- Rule 1: Buildings adjacent to AB with 3+ floors and similar height become AB
DO $$
DECLARE
    updated_count INTEGER := 1;
BEGIN
    WHILE updated_count > 0 LOOP
        WITH candidates AS (
            SELECT DISTINCT n.a_id
            FROM pylovo_input.neighbors n
            JOIN pylovo_input.building nb ON n.b_id = nb.id
            JOIN pylovo_input.building b1 ON n.a_id = b1.id
            WHERE nb.building_type = 'AB'
            --AND b1.floor_number >= 3
            --AND ABS(b1.height - nb.height)/GREATEST(b1.height, nb.height) < 0.2
            AND b1.building_use = 'residential'
            AND b1.building_type IS NULL
        )
        UPDATE pylovo_input.building b
        SET building_type = 'AB'
        FROM candidates
        WHERE b.id = candidates.a_id;

        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE 'Rule 1 iteration: % buildings updated', updated_count;
    END LOOP;
END $$;

-- Single Family Houses (SFH):
-- Typically have larger floor area, 1-2 floors, and few or no neighbors

UPDATE pylovo_input.building
SET building_type = 'SFH'
WHERE building_use = 'residential'
  AND building_type IS NULL
  AND ((floor_area < 350 AND floor_number <= 3 AND
        NOT EXISTS (SELECT 1
                    FROM pylovo_input.neighbors
                    WHERE pylovo_input.neighbors.a_id = pylovo_input.building.id)) OR
       (floor_area < 200 AND floor_number <= 2 AND
        NOT EXISTS (SELECT 1
                    FROM pylovo_input.neighbor_counts
                    WHERE pylovo_input.neighbor_counts.id = pylovo_input.building.id
                      AND count >= 2)));

-- Rule 2: Small buildings with floor area < 100 next to SFH likely also SFH
DO $$
DECLARE
    updated_count INTEGER := 1;
BEGIN
    WHILE updated_count > 0 LOOP
        WITH candidates AS (
            SELECT DISTINCT n.a_id
            FROM pylovo_input.neighbors n
            JOIN pylovo_input.building b1 ON n.a_id = b1.id
            JOIN pylovo_input.building b2 ON n.b_id = b2.id
            WHERE b2.building_type = 'SFH'
            AND b1.floor_area < 100
            AND b1.floor_number <= 2
            AND b1.building_use = 'residential'
            AND b1.building_type IS NULL
        )
        UPDATE pylovo_input.building b
        SET building_type = 'SFH'
        FROM candidates
        WHERE b.id = candidates.a_id;

        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE 'Rule 2 iteration: % buildings updated', updated_count;
    END LOOP;
END $$;

-- Terraced Houses (TH):
-- Typically have a medium floor area, 2-3 floors, and exactly 1-2 neighbors
-- They also tend to have similar floor area to their neighbors (within 20%)
UPDATE pylovo_input.building
SET building_type = 'TH'
WHERE building_use = 'residential'
  AND building_type IS NULL
  AND ((floor_area BETWEEN 80 AND 150 AND floor_number BETWEEN 2 AND 3 AND
        EXISTS (SELECT 1
                FROM pylovo_input.neighbor_counts
                WHERE pylovo_input.neighbor_counts.id = pylovo_input.building.id
                  AND count BETWEEN 1 AND 2) AND
        EXISTS (SELECT 1
                FROM pylovo_input.neighbors
                WHERE pylovo_input.neighbors.a_id = pylovo_input.building.id
                  AND ABS(pylovo_input.neighbors.a_area - pylovo_input.neighbors.b_area) /
                      GREATEST(pylovo_input.neighbors.a_area, pylovo_input.neighbors.b_area) < 0.2))
    );

-- Rule 3: Buildings adjacent to at least 2 THs with similar floor area become TH
DO $$
DECLARE
    updated_count INTEGER := 1;
BEGIN
    WHILE updated_count > 0 LOOP
        WITH candidates AS (
            SELECT DISTINCT n.a_id
            FROM pylovo_input.neighbors n
            JOIN pylovo_input.building nb ON n.b_id = nb.id
            JOIN pylovo_input.building b1 ON n.a_id = b1.id
            WHERE nb.building_type = 'TH'
            AND ABS(n.a_area - n.b_area)/GREATEST(n.a_area, n.b_area) < 0.25
            AND b1.building_use = 'residential'
            AND b1.building_type IS NULL
            GROUP BY n.a_id
            HAVING COUNT(*) >= 2
        )
        UPDATE pylovo_input.building b
        SET building_type = 'TH'
        FROM candidates
        WHERE b.id = candidates.a_id;

        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE 'Rule 3 iteration: % buildings updated', updated_count;
    END LOOP;
END $$;

-- Rule 4: Row of buildings with similar floor area and height likely TH
DO $$
DECLARE
    updated_count INTEGER := 1;
BEGIN
    WHILE updated_count > 0 LOOP
        WITH candidates AS (
            SELECT DISTINCT n.a_id
            FROM pylovo_input.neighbors n
            JOIN pylovo_input.building b1 ON n.a_id = b1.id
            JOIN pylovo_input.building b2 ON n.b_id = b2.id
            WHERE b2.building_type = 'TH'
            AND b1.floor_number = b2.floor_number
            AND ABS(b1.floor_area - b2.floor_area)/GREATEST(b1.floor_area, b2.floor_area) < 0.2
            AND b1.building_use = 'residential'
            AND b1.building_type IS NULL
        )
        UPDATE pylovo_input.building b
        SET building_type = 'TH'
        FROM candidates
        WHERE b.id = candidates.a_id;

        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE 'Rule 4 iteration: % buildings updated', updated_count;
    END LOOP;
END $$;

-- Multi-Family Houses (MFH):
-- Buildings with 2-3 floors, multiple units but smaller than apartment buildings
-- Often have some neighbors but not as many as apartment buildings
UPDATE pylovo_input.building
SET building_type = 'MFH'
WHERE building_use = 'residential'
  AND building_type IS NULL
  AND ((floor_number BETWEEN 2 AND 3 OR
        (floor_area > 150 AND
         EXISTS (SELECT 1
                 FROM pylovo_input.neighbor_counts
                 WHERE pylovo_input.neighbor_counts.id = pylovo_input.building.id
                   AND count BETWEEN 1 AND 3))
    ));

-- Rule 5: Buildings with 2-3 floors adjacent to MFH likely also MFH
DO $$
DECLARE
    updated_count INTEGER := 1;
BEGIN
    WHILE updated_count > 0 LOOP
        WITH candidates AS (
            SELECT DISTINCT n.a_id
            FROM pylovo_input.neighbors n
            JOIN pylovo_input.building b1 ON n.a_id = b1.id
            JOIN pylovo_input.building b2 ON n.b_id = b2.id
            WHERE b2.building_type = 'MFH'
            --AND b1.floor_number BETWEEN 2 AND 3
            AND b1.building_use = 'residential'
            AND b1.building_type IS NULL
        )
        UPDATE pylovo_input.building b
        SET building_type = 'MFH'
        FROM candidates
        WHERE b.id = candidates.a_id;

        GET DIAGNOSTICS updated_count = ROW_COUNT;
        RAISE NOTICE 'Rule 5 iteration: % buildings updated', updated_count;
    END LOOP;
END $$;

-- Set rest to AB
UPDATE pylovo_input.building b
SET building_type = 'AB'
WHERE b.building_use = 'residential' AND b.building_type IS NULL;