-- Add a customized postcode entry to the database by defining a polygon of arbitrary coordinates

INSERT INTO pylovo.postcode (postcode_id, plz, note, qkm, population, geom)
VALUES (
    99999,
    99999,
    '91301',
    99999,
    99999,
    ST_Transform(
        ST_SetSRID(
            ST_Multi(
                ST_GeomFromText('POLYGON((
                    11.3580 48.2575,
                    11.3775 48.2575,
                    11.3775 48.2440,
                    11.3580 48.2440,
                    11.3580 48.2575
                ))')
            ),
            4326
        ),
        3035
    )
);