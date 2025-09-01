-- Add a customized postcode entry to the database by defining a polygon of arbitrary coordinates

INSERT INTO pylovo.postcode (postcode_id, plz, note, qkm, population, geom)
VALUES (
    9999,
    '9999',
    'test review',
    9999,
    9999,
    ST_Transform(
        ST_SetSRID(
            ST_Multi(
                ST_GeomFromText('POLYGON((
                    11.0278000 49.7345000,
                    11.0560000 49.7345000,
                    11.0560000 49.7100000,
                    11.0278000 49.7100000,
                    11.0278000 49.7345000
                ))')
            ),
            4326
        ),
        3035
    )
);