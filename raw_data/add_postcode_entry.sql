-- Add a customized postcode entry to the database by defining a polygon of arbitrary coordinates

INSERT INTO pylovo.postcode (postcode_id, plz, testing_plz, note, qkm, population, geom)
VALUES (
    99999,
    99999,
    91301,
    'Forchheim testing covering Buckenhofen',
    99999,
    99999,
    ST_Transform(
        ST_SetSRID(
            ST_Multi(
                ST_GeomFromText('POLYGON((
                    11.0278000 49.7360000,
                    11.0560000 49.7360000,
                    11.0560000 49.7090000,
                    11.0278000 49.7090000,
                    11.0278000 49.7360000
                ))')
            ),
            4326
        ),
        3035
    )
);