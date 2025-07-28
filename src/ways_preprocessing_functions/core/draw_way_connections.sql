--
-- Name: draw_way_connections(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE OR REPLACE FUNCTION draw_way_connections() RETURNS void
    LANGUAGE PLPGSQL
AS
$$
declare
    way               RECORD;
    interpolate_point RECORD;
    old_street        RECORD;
begin
    -- Iterating buildings
    for way in
        SELECT geom, clazz, way_id
        FROM ways_tem
        loop
            --Finde Hausanschluss -> new_line
            SELECT geom, clazz, way_id
            INTO old_street
            FROM ways_tem as w
            WHERE ST_Intersects(ST_LineSubstring(way.geom, 0.01, 0.99), w.geom) -- begrenzen
              AND w.way_id != way.way_id
            LIMIT 1;

            IF NOT FOUND THEN
                continue;
            END IF;

            -- check whether the intersection of ST_Buffer(way.geom,0.1) , old_street.geom is a line
            -- this is necessary for the next SELECT statement with ST_LineInterpolatePoint()-function
            IF ST_Geometrytype(ST_Intersection(ST_Buffer(way.geom, 0.1), old_street.geom)) != 'ST_LineString' THEN
                RAISE NOTICE 'Value: %', old_street.geom;
                continue;
            END IF;

            SELECT ST_LineInterpolatePoint(ST_Intersection(ST_Buffer(way.geom, 0.1), old_street.geom), 0.5) AS geom
            INTO interpolate_point;

            DELETE
            FROM ways_tem
            WHERE way_id = old_street.way_id;

            -- INSERT new streets as two part of old street
            -- 	first half
            INSERT INTO ways_tem (way_id, clazz, geom)
            SELECT Max(way_id) + 1, --unique id guarenteed
                   old_street.clazz,
                   ST_LineSubstring(old_street.geom, 0, ST_LineLocatePoint(
                           old_street.geom, interpolate_point.geom))
            FROM ways_tem;
            --  second half
            INSERT INTO ways_tem (way_id, clazz, geom)
            SELECT Max(way_id) + 1,
                   old_street.clazz,
                   ST_LineSubstring(old_street.geom, ST_LineLocatePoint(
                           old_street.geom, interpolate_point.geom), 1)
            FROM ways_tem;

            DELETE
            FROM ways_tem
            WHERE way_id = way.way_id;

            INSERT INTO ways_tem (way_id, clazz, geom)
            SELECT Max(way_id) + 1, --unique id guarenteed
                   way.clazz,
                   ST_LineSubstring(way.geom, 0, ST_LineLocatePoint(
                           way.geom, interpolate_point.geom))
            FROM ways_tem;
            --  second half
            INSERT INTO ways_tem (way_id, clazz, geom)
            SELECT Max(way_id) + 1,
                   way.clazz,
                   ST_LineSubstring(way.geom, ST_LineLocatePoint(
                           way.geom, interpolate_point.geom), 1)
            FROM ways_tem;

        end loop;
    raise notice 'Home connections are drawn successfully...';
end;
$$;