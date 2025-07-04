-- Step 1: Add the column to hold closest way ID
ALTER TABLE pylovo_input.buildings_combined
ADD COLUMN IF NOT EXISTS closest_way_id INTEGER;

-- Step 2: Create helpful indexes
CREATE INDEX IF NOT EXISTS idx_way_names_name ON pylovo_input.way_names(name);
CREATE INDEX IF NOT EXISTS idx_way_names_name_kurz ON pylovo_input.way_names(name_kurz);
CREATE INDEX IF NOT EXISTS idx_way_names_way_id ON pylovo_input.way_names(way_id);

CREATE INDEX IF NOT EXISTS idx_ways_geom ON pylovo_input.ways USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_buildings_combined_geom ON pylovo_input.buildings_combined USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_building_addresses_id ON pylovo_input.building_addresses(building_id);

-- Step 3: Create a temporary table holding the closest way ID for each building
DROP TABLE IF EXISTS temp_closest_ways;
CREATE TEMP TABLE temp_closest_ways AS
SELECT
    ba.building_id,
    w.id AS closest_way_id
FROM pylovo_input.building_addresses AS ba
JOIN pylovo_input.buildings_combined AS b ON ba.building_id = b.id
JOIN pylovo_input.way_names wn ON ba.street = wn.name OR ba.street = wn.name_kurz
JOIN LATERAL (
    SELECT w.id, w.geom
    FROM pylovo_input.ways AS w
    WHERE w.id = wn.way_id
    ORDER BY w.geom <-> b.geom
    LIMIT 1
) w ON true;

-- Step 4: Reset all values to NULL
UPDATE pylovo_input.buildings_combined
SET closest_way_id = NULL;

-- Step 5: Update buildings_combined with closest way ID
UPDATE pylovo_input.buildings_combined AS b
SET closest_way_id = t.closest_way_id
FROM temp_closest_ways AS t
WHERE b.id = t.building_id;
