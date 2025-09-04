-- Add testing postcode entries within Forchheim area for testing the new config structure

-- Test postcode 1: Small area in Forchheim center
INSERT INTO pylovo.postcode (postcode_id, plz, testing_plz, note, qkm, population, geom)
VALUES (
    88888,
    88888,
    91301,
    'Forchheim testing area 1 - center',
    1.0,
    1000,
    ST_Transform(
        ST_SetSRID(
            ST_Multi(
                ST_GeomFromText('POLYGON((
                    11.0300000 49.7200000,
                    11.0400000 49.7200000,
                    11.0400000 49.7300000,
                    11.0300000 49.7300000,
                    11.0300000 49.7200000
                ))')
            ),
            4326
        ),
        3035
    )
);

-- Test postcode 2: Small area in Forchheim north
INSERT INTO pylovo.postcode (postcode_id, plz, testing_plz, note, qkm, population, geom)
VALUES (
    88889,
    88889,
    91301,
    'Forchheim testing area 2 - north',
    1.0,
    1000,
    ST_Transform(
        ST_SetSRID(
            ST_Multi(
                ST_GeomFromText('POLYGON((
                    11.0450000 49.7400000,
                    11.0550000 49.7400000,
                    11.0550000 49.7500000,
                    11.0450000 49.7500000,
                    11.0450000 49.7400000
                ))')
            ),
            4326
        ),
        3035
    )
);
