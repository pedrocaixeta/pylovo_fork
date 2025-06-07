-- drops
DROP MATERIALIZED VIEW pylovo_input.neighbor_counts;
DROP MATERIALIZED VIEW pylovo_input.neighbors;
DROP TABLE pylovo_input.building;

CREATE OR REPLACE FUNCTION pylovo_input.classify_building_use(funktion TEXT)
    RETURNS TEXT AS
$$
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

        ELSE RAISE EXCEPTION 'Unknown building function code: %', funktion;
        END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE
                    STRICT;


CREATE TABLE pylovo_input.building
(
    id                bigint PRIMARY KEY,
    objectid          text UNIQUE,
    height            double precision,
    floor_area        double precision,
    floor_number      int,
    building_use      text,
    building_use_id   text,
    building_type     text,
    occupants         int,
    households        int,
    construction_year text,
    geom              geometry(MultiPolygon, 3035),
    grid_id           text
);

CREATE INDEX IF NOT EXISTS building_geom_idx ON pylovo_input.building USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_type_check ON pylovo_input.building (id, building_type, building_use);

-- fill id, objectid and building use columns
INSERT INTO pylovo_input.building (id, objectid, building_use, building_use_id)
SELECT f.id,
       f.objectid,
       pylovo_input.classify_building_use(p.val_string) as building_use,
       p.val_string                                     as building_use_id
FROM feature f
         JOIN property p ON f.id = p.feature_id
WHERE f.objectclass_id = 901
  AND p.namespace_id = 10
  AND p.name = 'function'
  AND p.val_string LIKE '31001_%'  -- only allow buildings
  AND p.val_string <> '31001_2463' -- exclude garages
  AND p.val_string <> '31001_2513' -- exclude water containers
ORDER BY f.id;

-- fill height column
WITH height_data AS (SELECT p.feature_id, p.val_double
                     FROM property p
                     WHERE p.name = 'value'
                       AND p.parent_id IN (SELECT id FROM property WHERE name = 'height'))
UPDATE pylovo_input.building
SET height = hd.val_double
FROM height_data hd
WHERE id = hd.feature_id;

-- delete buildings below a height threshold
DELETE
FROM pylovo_input.building
WHERE height < 3.5;

-- fill geom and floor_area columns
WITH ground_data AS (SELECT regexp_replace(f.objectid, '_[^_]*-.*$', '') as building_objectid,
                            cast(p.val_string as double precision)       as area,
                            ST_Transform(ST_Force2D(gd.geometry), 3035)  as geometry
                     FROM feature f
                              JOIN geometry_data gd ON f.id = gd.feature_id
                              JOIN property p ON gd.feature_id = p.feature_id
                     WHERE f.objectclass_id = 710
                       AND -- GroundSurface
                         p.name = 'Flaeche')
UPDATE pylovo_input.building
SET floor_area = gd.area,
    geom       = gd.geometry
FROM ground_data gd
WHERE objectid = building_objectid;

-- delete buildings below an area threshold
DELETE
FROM pylovo_input.building
WHERE building.floor_area < 15
   OR (building.floor_area * height) < 150;

-- fill floor_number column
WITH floor_number_data AS (SELECT feature_id, val_int
                           FROM property
                           WHERE name = 'storeysAboveGround')
UPDATE pylovo_input.building
SET floor_number = fnd.val_int
FROM floor_number_data fnd
WHERE id = fnd.feature_id;

-- fill in missing floor_number values
WITH average_floor_height AS (SELECT building_use_id,
                                     PERCENTILE_CONT(0.5) WITHIN GROUP ( ORDER BY (height / floor_number) ) as height_per_floor
                              FROM pylovo_input.building
                              GROUP BY building_use_id)
UPDATE pylovo_input.building b
SET floor_number = ROUND(height / COALESCE(afh.height_per_floor, height))
FROM average_floor_height afh
WHERE b.floor_number IS NULL
  AND b.building_use_id = afh.building_use_id;


-- create neighborhood views
CREATE MATERIALIZED VIEW pylovo_input.neighbors AS
SELECT a.id         AS a_id,
       b.id         AS b_id,
       a.floor_area AS a_area,
       b.floor_area AS b_area
FROM pylovo_input.building a
         JOIN pylovo_input.building b ON
    a.id != b.id AND
    a.building_use = 'residential' AND
    b.building_use = 'residential' AND
    a.geom && b.geom AND -- check for bbox intersection
    ST_DWithin(a.geom, b.geom, 0.01);

-- also includes counts of 0
CREATE MATERIALIZED VIEW pylovo_input.neighbor_counts AS
SELECT b.id as id, count(b_id) as count
FROM pylovo_input.building b
         LEFT JOIN pylovo_input.neighbors n ON b.id = n.a_id
GROUP BY b.id;

-- assign grid id for later use
UPDATE pylovo_input.building
SET grid_id = w.gitter_id_100m
FROM census2022.wohnungen_nach_gebaeudetyp_groesse w
WHERE ST_Contains(w.geometry, ST_Centroid(geom));


-- fill occupants
-- Step 1: Create temp table for buildings with cell and weight
DROP TABLE IF EXISTS temp_building_weights;
CREATE TEMP TABLE temp_building_weights AS
SELECT b.id                    AS building_id,
       b.height * b.floor_area AS weight,
       v.gitter_id_100m,
       v.einwohner
FROM pylovo_input.building b
         JOIN census2022.bevoelkerungszahl v
              ON ST_Intersects(v.geometry, b.geom)
WHERE building_use = 'residential';

-- Step 2: Create temp table for total weights per grid cell
DROP TABLE IF EXISTS temp_cell_weights;
DROP TABLE IF EXISTS temp_cell_weights;
CREATE TEMP TABLE temp_cell_weights AS
SELECT gitter_id_100m,
       SUM(weight) AS total_weight
FROM temp_building_weights
GROUP BY gitter_id_100m;

-- Step 3: Assign occupants proportionally to each building
DROP TABLE IF EXISTS temp_building_occupants;
CREATE TEMP TABLE temp_building_occupants AS
SELECT bw.building_id,
       bw.weight,
       bw.gitter_id_100m,
       bw.einwohner,
       cw.total_weight,
       CASE
           WHEN cw.total_weight > 0 THEN ROUND((bw.weight / cw.total_weight) * bw.einwohner)::int
           ELSE 0
           END AS assigned_occupants
FROM temp_building_weights bw
         JOIN temp_cell_weights cw
              ON bw.gitter_id_100m = cw.gitter_id_100m;

-- Step 4: Update the original building table
UPDATE pylovo_input.building b
SET occupants = bo.assigned_occupants
FROM temp_building_occupants bo
WHERE b.id = bo.building_id;


-- fill households
-- Step 1: Create temp table linking buildings to avg household size grid
DROP TABLE IF EXISTS temp_building_hh_grid;
CREATE TEMP TABLE temp_building_hh_grid AS
SELECT b.id AS building_id,
       b.occupants,
       d.durchschnhhgroesse
FROM pylovo_input.building b
         JOIN census2022.durchschn_haushaltsgroesse d
              ON ST_Intersects(d.geometry, b.geom)
WHERE b.occupants IS NOT NULL
  AND b.building_use = 'residential' -- already ensured by above clause
  AND d.durchschnhhgroesse IS NOT NULL
  AND d.durchschnhhgroesse > 0;

-- Step 2: Compute households per building
DROP TABLE IF EXISTS temp_building_households;
CREATE TEMP TABLE temp_building_households AS
SELECT building_id,
       occupants,
       durchschnhhgroesse,
       GREATEST(ROUND(occupants / durchschnhhgroesse)::int, 1) AS estimated_households
FROM temp_building_hh_grid;

-- Step 3: Update original building table
UPDATE pylovo_input.building b
SET households = bh.estimated_households
FROM temp_building_households bh
WHERE b.id = bh.building_id;

-- fill construction_year
-- Step 1: Create a table with joined buildings and grid cells
DROP TABLE IF EXISTS temp_building_with_grid_year;
CREATE TEMP TABLE temp_building_with_grid_year AS
SELECT b.id   AS building_id,
       b.geom AS building_geom,
       g.*
FROM pylovo_input.building b
         JOIN
     census2022.gebaeude_nach_baujahr_in_mikrozensus_klassen g
     ON
         ST_Intersects(b.geom, g.geometry)
WHERE g.gitter_id_100m IS NOT NULL;


-- Step 2: Assign construction year using weighted random distribution
-- min year = 1800
-- Note: This version uses a WITH clause to prepare weights and cumulative ranges.
--       Then assigns a construction_year based on a random number weighted by those counts.
UPDATE pylovo_input.building b
SET construction_year = sub.assigned_year
FROM (SELECT building_id,
             CASE
                 WHEN total > 0 THEN (
                     -- Normalize weights and generate a random year within the matched bin
                     CASE
                         WHEN r < vor1919 / total THEN '-1919'
                         WHEN r < (vor1919 + a1919bis1948) / total THEN '1919-1948'
                         WHEN r < (vor1919 + a1919bis1948 + a1949bis1978) / total
                             THEN '1949-1978'
                         WHEN r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990) / total
                             THEN '1979-1990'
                         WHEN r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000) / total
                             THEN '1991-2000'
                         WHEN r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000 + a2001bis2010) /
                                  total THEN '2001-2010'
                         WHEN r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000 + a2001bis2010 +
                                   a2011bis2019) / total THEN '2011-2019'
                         ELSE '2020-'
                         END
                     )
                 ELSE NULL
                 END AS assigned_year
      FROM (SELECT building_id,
                   vor1919,
                   a1919bis1948,
                   a1949bis1978,
                   a1979bis1990,
                   a1991bis2000,
                   a2001bis2010,
                   a2011bis2019,
                   a2020undspaeter,
                   (COALESCE(vor1919, 0) +
                    COALESCE(a1919bis1948, 0) +
                    COALESCE(a1949bis1978, 0) +
                    COALESCE(a1979bis1990, 0) +
                    COALESCE(a1991bis2000, 0) +
                    COALESCE(a2001bis2010, 0) +
                    COALESCE(a2011bis2019, 0) +
                    COALESCE(a2020undspaeter, 0)) AS total,
                   random()                       AS r
            FROM temp_building_with_grid_year) year_probs) sub
WHERE b.id = sub.building_id;


-- fill building_type
-- Step 1: Apartment Buildings (AB):
-- Typically have <4+ floors and many neighbors> or <3+ floors and 3+ neighbors> or <floor area > 1500>
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

-- Buildings adjacent to AB with 3+ floors and similar height become AB
DO
$$
    DECLARE
        updated_count INTEGER := 1;
    BEGIN
        WHILE updated_count > 0
            LOOP
                WITH candidates AS (SELECT DISTINCT n.a_id
                                    FROM pylovo_input.neighbors n
                                             JOIN pylovo_input.building nb ON n.b_id = nb.id
                                             JOIN pylovo_input.building b1 ON n.a_id = b1.id
                                    WHERE nb.building_type = 'AB'
                                      --AND b1.floor_number >= 3
                                      --AND ABS(b1.height - nb.height)/GREATEST(b1.height, nb.height) < 0.2
                                      AND b1.building_use = 'residential'
                                      AND b1.building_type IS NULL)
                UPDATE pylovo_input.building b
                SET building_type = 'AB'
                FROM candidates
                WHERE b.id = candidates.a_id;

                GET DIAGNOSTICS updated_count = ROW_COUNT;
                -- RAISE NOTICE 'Rule 1 iteration: % buildings updated', updated_count;
            END LOOP;
    END
$$;

-- Step 2: Single Family Houses (SFH):
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

-- Small buildings with floor area < 100 next to SFH likely also SFH
DO
$$
    DECLARE
        updated_count INTEGER := 1;
    BEGIN
        WHILE updated_count > 0
            LOOP
                WITH candidates AS (SELECT DISTINCT n.a_id
                                    FROM pylovo_input.neighbors n
                                             JOIN pylovo_input.building b1 ON n.a_id = b1.id
                                             JOIN pylovo_input.building b2 ON n.b_id = b2.id
                                    WHERE b2.building_type = 'SFH'
                                      AND b1.floor_area < 100
                                      AND b1.floor_number <= 2
                                      AND b1.building_use = 'residential'
                                      AND b1.building_type IS NULL)
                UPDATE pylovo_input.building b
                SET building_type = 'SFH'
                FROM candidates
                WHERE b.id = candidates.a_id;

                GET DIAGNOSTICS updated_count = ROW_COUNT;
                -- RAISE NOTICE 'Rule 2 iteration: % buildings updated', updated_count;
            END LOOP;
    END
$$;

-- Step 3: Terraced Houses (TH):
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

-- Buildings adjacent to at least 2 THs with similar floor area become TH
DO
$$
    DECLARE
        updated_count INTEGER := 1;
    BEGIN
        WHILE updated_count > 0
            LOOP
                WITH candidates AS (SELECT DISTINCT n.a_id
                                    FROM pylovo_input.neighbors n
                                             JOIN pylovo_input.building nb ON n.b_id = nb.id
                                             JOIN pylovo_input.building b1 ON n.a_id = b1.id
                                    WHERE nb.building_type = 'TH'
                                      AND ABS(n.a_area - n.b_area) / GREATEST(n.a_area, n.b_area) < 0.25
                                      AND b1.building_use = 'residential'
                                      AND b1.building_type IS NULL
                                    GROUP BY n.a_id
                                    HAVING COUNT(*) >= 2)
                UPDATE pylovo_input.building b
                SET building_type = 'TH'
                FROM candidates
                WHERE b.id = candidates.a_id;

                GET DIAGNOSTICS updated_count = ROW_COUNT;
                -- RAISE NOTICE 'Rule 3 iteration: % buildings updated', updated_count;
            END LOOP;
    END
$$;

-- Row of buildings with similar floor area and height likely TH
DO
$$
    DECLARE
        updated_count INTEGER := 1;
    BEGIN
        WHILE updated_count > 0
            LOOP
                WITH candidates AS (SELECT DISTINCT n.a_id
                                    FROM pylovo_input.neighbors n
                                             JOIN pylovo_input.building b1 ON n.a_id = b1.id
                                             JOIN pylovo_input.building b2 ON n.b_id = b2.id
                                    WHERE b2.building_type = 'TH'
                                      AND b1.floor_number = b2.floor_number
                                      AND ABS(b1.floor_area - b2.floor_area) / GREATEST(b1.floor_area, b2.floor_area) <
                                          0.2
                                      AND b1.building_use = 'residential'
                                      AND b1.building_type IS NULL)
                UPDATE pylovo_input.building b
                SET building_type = 'TH'
                FROM candidates
                WHERE b.id = candidates.a_id;

                GET DIAGNOSTICS updated_count = ROW_COUNT;
                -- RAISE NOTICE 'Rule 4 iteration: % buildings updated', updated_count;
            END LOOP;
    END
$$;

-- Step 4: Multi-Family Houses (MFH):
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

-- Buildings with 2-3 floors adjacent to MFH likely also MFH
DO
$$
    DECLARE
        updated_count INTEGER := 1;
    BEGIN
        WHILE updated_count > 0
            LOOP
                WITH candidates AS (SELECT DISTINCT n.a_id
                                    FROM pylovo_input.neighbors n
                                             JOIN pylovo_input.building b1 ON n.a_id = b1.id
                                             JOIN pylovo_input.building b2 ON n.b_id = b2.id
                                    WHERE b2.building_type = 'MFH'
                                      --AND b1.floor_number BETWEEN 2 AND 3
                                      AND b1.building_use = 'residential'
                                      AND b1.building_type IS NULL)
                UPDATE pylovo_input.building b
                SET building_type = 'MFH'
                FROM candidates
                WHERE b.id = candidates.a_id;

                GET DIAGNOSTICS updated_count = ROW_COUNT;
                -- RAISE NOTICE 'Rule 5 iteration: % buildings updated', updated_count;
            END LOOP;
    END
$$;

-- Step 5: Set rest to AB
UPDATE pylovo_input.building b
SET building_type = 'AB'
WHERE b.building_use = 'residential'
  AND b.building_type IS NULL;


-- fix wrong assignments
UPDATE pylovo_input.building b
SET building_type = 'SFH'
FROM pylovo_input.neighbor_counts nc
WHERE b.id = nc.id
  AND building_type IN ('MFH', 'AB')
  AND households = 1
  AND nc.count = 0;

UPDATE pylovo_input.building b
SET building_type = 'TH'
FROM pylovo_input.neighbor_counts nc
WHERE b.id = nc.id
  AND building_type IN ('MFH', 'AB')
  AND households = 1
  AND nc.count != 0;

UPDATE pylovo_input.building b
SET building_type = 'MFH'
FROM pylovo_input.neighbor_counts nc
WHERE b.id = nc.id
  AND building_type IN ('SFH', 'TH')
  AND households BETWEEN 2 AND 4;

UPDATE pylovo_input.building b
SET building_type = 'AB'
FROM pylovo_input.neighbor_counts nc
WHERE b.id = nc.id
  AND building_type IN ('SFH', 'TH')
  AND households >= 5;


-- Rebalance according to census data
-- This script rebalances residential building types according to reference data

-- Step 1: Create a mapping between building types and reference columns
-- AB (Apartment Buildings) = mfh_13undmehrwohnungen + mfh_7bis12wohnungen
-- MFH (Multi-Family Houses) = mfh_3bis6wohnungen + freist_zfh + zfh_dhh
-- TH (Terraced Houses) = efh_reihenhaus + zfh_reihenhaus
-- SFH (Single Family Houses) = freiefh + efh_dhh

-- Step 2: Calculate current distribution and target distribution per grid
DROP TABLE IF EXISTS temp_grid_current;
CREATE TABLE temp_grid_current AS
WITH grid_current AS (
    SELECT
        w.gitter_id_100m as grid_id,
        COUNT(CASE WHEN b.building_type = 'AB' THEN 1 END) as current_ab,
        COUNT(CASE WHEN b.building_type = 'MFH' THEN 1 END) as current_mfh,
        COUNT(CASE WHEN b.building_type = 'TH' THEN 1 END) as current_th,
        COUNT(CASE WHEN b.building_type = 'SFH' THEN 1 END) as current_sfh,
        COUNT(*) as total_buildings
    FROM pylovo_input.building b
    JOIN census2022.wohnungen_nach_gebaeudetyp_groesse w ON ST_Contains(w.geometry, ST_Centroid(b.geom))
    WHERE b.building_use = 'residential' AND w.gitter_id_100m IS NOT NULL
    GROUP BY w.gitter_id_100m
)
SELECT * FROM grid_current;

DROP TABLE IF EXISTS temp_grid_target;
CREATE TABLE temp_grid_target AS (
    SELECT
        gitter_id_100m as grid_id,
        -- Calculate target counts from reference data
        COALESCE(mfh_13undmehrwohnungen + mfh_7bis12wohnungen, 0) as target_ab,
        COALESCE(mfh_3bis6wohnungen + freist_zfh + zfh_dhh, 0) as target_mfh,
        COALESCE(efh_reihenhaus + zfh_reihenhaus, 0) as target_th,
        COALESCE(freiefh + efh_dhh, 0) as target_sfh,
        COALESCE(freiefh + efh_dhh + efh_reihenhaus + freist_zfh + zfh_dhh + zfh_reihenhaus + mfh_3bis6wohnungen + mfh_7bis12wohnungen + mfh_13undmehrwohnungen, 0)
            as total_target
    FROM census2022.wohnungen_nach_gebaeudetyp_groesse w
    WHERE gitter_id_100m IS NOT NULL
    AND EXISTS (
        SELECT 1
        FROM pylovo_input.building b
        WHERE b.grid_id = w.gitter_id_100m
    )
);

DROP TABLE IF EXISTS temp_grid_comparison;
CREATE TABLE temp_grid_comparison AS
WITH grid_comparison AS (
    SELECT
        gc.grid_id,
        gc.current_ab,
        gc.current_mfh,
        gc.current_th,
        gc.current_sfh,
        gc.total_buildings,
        gt.target_ab,
        gt.target_mfh,
        gt.target_th,
        gt.target_sfh,
        gt.total_target,
        -- Calculate needed adjustments (scaled to current total)
        CASE WHEN gt.total_target > 0 THEN
            ROUND(gt.target_ab * gc.total_buildings / gt.total_target) - gc.current_ab
        ELSE 0 END as ab_adjustment,
        CASE WHEN gt.total_target > 0 THEN
            ROUND(gt.target_mfh * gc.total_buildings / gt.total_target) - gc.current_mfh
        ELSE 0 END as mfh_adjustment,
        CASE WHEN gt.total_target > 0 THEN
            ROUND(gt.target_th * gc.total_buildings / gt.total_target) - gc.current_th
        ELSE 0 END as th_adjustment,
        CASE WHEN gt.total_target > 0 THEN
            ROUND(gt.target_sfh * gc.total_buildings / gt.total_target) - gc.current_sfh
        ELSE 0 END as sfh_adjustment
    FROM temp_grid_current gc
    LEFT JOIN temp_grid_target gt ON gc.grid_id = gt.grid_id
)
SELECT * FROM grid_comparison;

-- Step 3: Create unified conversion plan using window functions
DROP TABLE IF EXISTS temp_building_rankings;
CREATE TABLE temp_building_rankings AS (
    SELECT
        b.id,
        b.building_type,
        b.households,
        b.occupants,
        b.floor_area,
        b.height,
        gc.grid_id,
        gc.ab_adjustment,
        gc.mfh_adjustment,
        gc.th_adjustment,
        gc.sfh_adjustment,

        -- Rankings for conversion priorities
        -- For AB increases: prioritize largest MFH, then largest TH
        ROW_NUMBER() OVER (
            PARTITION BY gc.grid_id, b.building_type
            ORDER BY
                CASE WHEN b.building_type = 'MFH' THEN b.floor_area * b.height END DESC NULLS LAST,
                CASE WHEN b.building_type = 'TH' THEN b.floor_area * b.height END DESC NULLS LAST
        ) as ab_conversion_rank,

        -- For MFH increases: prioritize largest TH, then smallest AB
        ROW_NUMBER() OVER (
            PARTITION BY gc.grid_id, b.building_type
            ORDER BY
                CASE WHEN b.building_type = 'TH' THEN b.floor_area * b.height END DESC NULLS LAST,
                CASE WHEN b.building_type = 'AB' AND b.households <= 4 THEN b.floor_area * b.height END ASC NULLS LAST
        ) as mfh_conversion_rank,

        -- For TH increases: prioritize smaller MFH
        ROW_NUMBER() OVER (
            PARTITION BY gc.grid_id, b.building_type
            ORDER BY
                CASE WHEN b.building_type = 'MFH' AND b.households <= 2 THEN b.floor_area * b.height END ASC NULLS LAST
        ) as th_conversion_rank,

        -- For SFH increases: prioritize smaller TH, then smaller MFH
        ROW_NUMBER() OVER (
            PARTITION BY gc.grid_id, b.building_type
            ORDER BY
                CASE WHEN b.building_type = 'TH' THEN b.floor_area * b.height END ASC NULLS LAST,
                CASE WHEN b.building_type = 'MFH' AND b.households <= 2 THEN b.floor_area * b.height END ASC NULLS LAST
        ) as sfh_conversion_rank

    FROM pylovo_input.building b
    JOIN census2022.wohnungen_nach_gebaeudetyp_groesse w ON ST_Contains(w.geometry, ST_Centroid(b.geom))
    JOIN temp_grid_comparison gc ON w.gitter_id_100m = gc.grid_id
    WHERE b.building_use = 'residential'
      AND gc.total_target > 0
);

-- Pre-calculate the subquery values once per grid_id
DROP TABLE IF EXISTS temp_grid_counts;
CREATE TABLE temp_grid_counts AS (
    SELECT
        grid_id,
        COUNT(CASE WHEN building_type = 'MFH' AND households > 1 THEN 1 END) as mfh_multi_household_count,
        COUNT(CASE WHEN building_type = 'TH' THEN 1 END) as th_count
    FROM temp_building_rankings
    GROUP BY grid_id
);

-- Create the conversion decisions table with a single join
DROP TABLE IF EXISTS temp_conversion_decisions;
CREATE TABLE temp_conversion_decisions AS (
    SELECT
        br.id,
        br.building_type as original_type,
        br.households,
        br.occupants,
        br.grid_id,

        -- Determine new building type based on conversion needs and rankings
        CASE
            -- Convert to AB
            WHEN br.ab_adjustment > 0 AND (
                (br.building_type = 'MFH' AND br.households > 1 AND br.ab_conversion_rank <= br.ab_adjustment) OR
                (br.building_type = 'TH' AND br.ab_conversion_rank <= GREATEST(0, br.ab_adjustment - gc.mfh_multi_household_count))
            ) THEN 'AB'

            -- Convert to MFH
            WHEN br.mfh_adjustment > 0 AND (
                (br.building_type = 'TH' AND br.mfh_conversion_rank <= br.mfh_adjustment) OR
                (br.building_type = 'AB' AND br.households <= 4 AND br.mfh_conversion_rank <= GREATEST(0, br.mfh_adjustment - gc.th_count))
            ) THEN 'MFH'

            -- Convert to TH
            WHEN br.th_adjustment > 0 AND br.building_type = 'MFH' AND br.households <= 2 AND br.th_conversion_rank <= br.th_adjustment
            THEN 'TH'

            -- Convert to SFH
            WHEN br.sfh_adjustment > 0 AND (
                (br.building_type = 'TH' AND br.sfh_conversion_rank <= br.sfh_adjustment) OR
                (br.building_type = 'MFH' AND br.households <= 2 AND br.sfh_conversion_rank <= GREATEST(0, br.sfh_adjustment - gc.th_count))
            ) THEN 'SFH'

            ELSE br.building_type
        END as new_type,

        -- Calculate new household counts (same logic as before, just using pre-calculated values)
        CASE
            -- AB conversions
            WHEN br.ab_adjustment > 0 AND (
                (br.building_type = 'MFH' AND br.households > 1 AND br.ab_conversion_rank <= br.ab_adjustment) OR
                (br.building_type = 'TH' AND br.ab_conversion_rank <= GREATEST(0, br.ab_adjustment - gc.mfh_multi_household_count))
            ) THEN GREATEST(br.households, 2)

            -- MFH conversions
            WHEN br.mfh_adjustment > 0 AND (
                (br.building_type = 'TH' AND br.mfh_conversion_rank <= br.mfh_adjustment) OR
                (br.building_type = 'AB' AND br.households <= 4 AND br.mfh_conversion_rank <= GREATEST(0, br.mfh_adjustment - gc.th_count))
            ) THEN GREATEST(br.households, 2)

            -- SFH conversions
            WHEN br.sfh_adjustment > 0 AND (
                (br.building_type = 'TH' AND br.sfh_conversion_rank <= br.sfh_adjustment) OR
                (br.building_type = 'MFH' AND br.households <= 2 AND br.sfh_conversion_rank <= GREATEST(0, br.sfh_adjustment - gc.th_count))
            ) THEN 1

            ELSE br.households
        END as new_households

    FROM temp_building_rankings br
    JOIN temp_grid_counts gc ON br.grid_id = gc.grid_id
);


DROP TABLE IF EXISTS temp_conversion_plan;
CREATE TABLE temp_conversion_plan AS
(
    SELECT
        id,
        original_type,
        new_type,
        households,
        new_households,
        GREATEST(occupants, new_households, CASE WHEN new_type = 'AB' THEN 2 ELSE 1 END) as new_occupants
    FROM temp_conversion_decisions
    WHERE original_type != new_type
);

-- Step 4: Apply all conversions in a single batch update
UPDATE pylovo_input.building
SET
    building_type = cp.new_type,
    households = cp.new_households,
    occupants = cp.new_occupants
FROM temp_conversion_plan cp
WHERE building.id = cp.id;

-- Step 5: Generate final report

-- Pre-conversion state
DROP TABLE IF EXISTS temp_pre_conversion;
CREATE TABLE temp_pre_conversion AS
SELECT
    'Pre-Conversion' as phase,
    COUNT(CASE WHEN building_type = 'AB' THEN 1 END) as ab_count,
    COUNT(CASE WHEN building_type = 'MFH' THEN 1 END) as mfh_count,
    COUNT(CASE WHEN building_type = 'TH' THEN 1 END) as th_count,
    COUNT(CASE WHEN building_type = 'SFH' THEN 1 END) as sfh_count,
    COUNT(*) as total_count,
    -- Calculate percentages
    ROUND(COUNT(CASE WHEN building_type = 'AB' THEN 1 END) * 100.0 / COUNT(*), 1) as ab_pct,
    ROUND(COUNT(CASE WHEN building_type = 'MFH' THEN 1 END) * 100.0 / COUNT(*), 1) as mfh_pct,
    ROUND(COUNT(CASE WHEN building_type = 'TH' THEN 1 END) * 100.0 / COUNT(*), 1) as th_pct,
    ROUND(COUNT(CASE WHEN building_type = 'SFH' THEN 1 END) * 100.0 / COUNT(*), 1) as sfh_pct
FROM (
    SELECT
        CASE
            WHEN cp.original_type IS NOT NULL THEN cp.original_type
            ELSE b.building_type
        END as building_type
    FROM pylovo_input.building b
    LEFT JOIN temp_conversion_plan cp ON b.id = cp.id
    WHERE b.building_use = 'residential'
) pre_state;

-- Post-conversion state
DROP TABLE IF EXISTS temp_post_conversion;
CREATE TABLE temp_post_conversion AS
SELECT
    'Post-Conversion' as phase,
    COUNT(CASE WHEN building_type = 'AB' THEN 1 END) as ab_count,
    COUNT(CASE WHEN building_type = 'MFH' THEN 1 END) as mfh_count,
    COUNT(CASE WHEN building_type = 'TH' THEN 1 END) as th_count,
    COUNT(CASE WHEN building_type = 'SFH' THEN 1 END) as sfh_count,
    COUNT(*) as total_count,
    -- Calculate percentages
    ROUND(COUNT(CASE WHEN building_type = 'AB' THEN 1 END) * 100.0 / COUNT(*), 1) as ab_pct,
    ROUND(COUNT(CASE WHEN building_type = 'MFH' THEN 1 END) * 100.0 / COUNT(*), 1) as mfh_pct,
    ROUND(COUNT(CASE WHEN building_type = 'TH' THEN 1 END) * 100.0 / COUNT(*), 1) as th_pct,
    ROUND(COUNT(CASE WHEN building_type = 'SFH' THEN 1 END) * 100.0 / COUNT(*), 1) as sfh_pct
FROM pylovo_input.building
WHERE building_use = 'residential';

-- Target distribution
DROP TABLE IF EXISTS temp_target_summary;
CREATE TABLE temp_target_summary AS
SELECT
    'Target' as phase,
    SUM(target_ab) as ab_count,
    SUM(target_mfh) as mfh_count,
    SUM(target_th) as th_count,
    SUM(target_sfh) as sfh_count,
    SUM(total_target) as total_count,
    -- Calculate percentages based on census total
    ROUND(SUM(target_ab) * 100.0 / NULLIF(SUM(total_target), 0)) as ab_pct,
    ROUND(SUM(target_mfh) * 100.0 / NULLIF(SUM(total_target), 0)) as mfh_pct,
    ROUND(SUM(target_th) * 100.0 / NULLIF(SUM(total_target), 0)) as th_pct,
    ROUND(SUM(target_sfh) * 100.0 / NULLIF(SUM(total_target), 0)) as sfh_pct
FROM temp_grid_target;

-- Conversion summary
DROP TABLE IF EXISTS temp_conversion_summary;
CREATE TABLE temp_conversion_summary AS
SELECT
    original_type,
    new_type,
    COUNT(*) as conversion_count
FROM temp_conversion_plan
GROUP BY original_type, new_type
ORDER BY original_type, new_type;

-- Final Report
SELECT '=== BUILDING REBALANCING REPORT ===' as report_section;

-- Main summary with counts and percentages
SELECT
    phase,
    ab_count as "AB Count",
    CONCAT(ab_pct, '%') as "AB %",
    mfh_count as "MFH Count",
    CONCAT(mfh_pct, '%') as "MFH %",
    th_count as "TH Count",
    CONCAT(th_pct, '%') as "TH %",
    sfh_count as "SFH Count",
    CONCAT(sfh_pct, '%') as "SFH %",
    total_count as "Total"
FROM (
    SELECT * FROM temp_pre_conversion
    UNION ALL
    SELECT * FROM temp_post_conversion
    UNION ALL
    SELECT * FROM temp_target_summary
) combined_summary
ORDER BY
    CASE phase
        WHEN 'Pre-Conversion' THEN 1
        WHEN 'Post-Conversion' THEN 2
        WHEN 'Target' THEN 3
    END;

SELECT '=== CONVERSION DETAILS ===' as report_section;

SELECT
    original_type as "From Type",
    new_type as "To Type",
    conversion_count as "Buildings Converted"
FROM temp_conversion_summary;

SELECT '=== GRID ANALYSIS ===' as report_section;

SELECT '=== SUMMARY STATISTICS ===' as report_section;

SELECT
    'Total Grids Requiring Adjustment' as metric,
    COUNT(*) as value
FROM temp_grid_comparison
WHERE ABS(ab_adjustment) + ABS(mfh_adjustment) + ABS(th_adjustment) + ABS(sfh_adjustment) > 0
UNION ALL
SELECT
    'Total Buildings Converted' as metric,
    COUNT(*) as value
FROM temp_conversion_plan;