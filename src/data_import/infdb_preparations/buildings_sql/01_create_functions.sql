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

CREATE OR REPLACE FUNCTION pylovo_input.assign_weighted_year(
    vor1919 double precision,
    a1919bis1948 double precision,
    a1949bis1978 double precision,
    a1979bis1990 double precision,
    a1991bis2000 double precision,
    a2001bis2010 double precision,
    a2011bis2019 double precision,
    a2020undspaeter double precision,
    r double precision
) RETURNS TEXT AS $$
DECLARE
    total NUMERIC;
BEGIN
    total := vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000 + a2001bis2010 + a2011bis2019 + a2020undspaeter;

    IF total <= 0 THEN
        RETURN NULL;
    END IF;

    IF r < vor1919 / total THEN
        RETURN '-1919';
    ELSIF r < (vor1919 + a1919bis1948) / total THEN
        RETURN '1919-1948';
    ELSIF r < (vor1919 + a1919bis1948 + a1949bis1978) / total THEN
        RETURN '1949-1978';
    ELSIF r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990) / total THEN
        RETURN '1979-1990';
    ELSIF r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000) / total THEN
        RETURN '1991-2000';
    ELSIF r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000 + a2001bis2010) / total THEN
        RETURN '2001-2010';
    ELSIF r < (vor1919 + a1919bis1948 + a1949bis1978 + a1979bis1990 + a1991bis2000 + a2001bis2010 + a2011bis2019) / total THEN
        RETURN '2011-2019';
    ELSE
        RETURN '2020-';
    END IF;
END;
$$ LANGUAGE plpgsql;