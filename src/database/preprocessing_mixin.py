import json
import warnings
from abc import ABC

from src.config_loader import *
from src.database.base_mixin import BaseMixin

warnings.simplefilter(action='ignore', category=UserWarning)


class PreprocessingMixin(BaseMixin, ABC):
    def __init__(self):
        super().__init__()

    def insert_parameter_tables(self, consumer_categories: pd.DataFrame):
        self.cur.execute("SELECT count(*) FROM consumer_categories")
        categories_exist = self.cur.fetchone()[0]
        with self.sqla_engine.begin() as conn:
            if not categories_exist:
                consumer_categories.to_sql(name="consumer_categories", con=conn, if_exists="append", index=False)
                self.logger.debug("Parameter tables are inserted")

    def insert_version_if_not_exists(self):
        count_query = f"""SELECT COUNT(*) 
            FROM version 
            WHERE "version_id" = '{VERSION_ID}'"""
        self.cur.execute(count_query)
        version_exists = self.cur.fetchone()[0]
        if not version_exists:
            # create new version
            consumer_categories_str = CONSUMER_CATEGORIES.to_json().replace("'", "''")
            cable_cost_dict_str = json.dumps(CABLE_COST_DICT).replace("'", "''")
            connection_available_cables_str = str(CONNECTION_AVAILABLE_CABLES).replace("'", "''")
            other_parameters_dict = {"LARGE_COMPONENT_LOWER_BOUND": LARGE_COMPONENT_LOWER_BOUND,
                                     "LARGE_COMPONENT_DIVIDER": LARGE_COMPONENT_DIVIDER, "VN": VN,
                                     "V_BAND_LOW": V_BAND_LOW, "V_BAND_HIGH": V_BAND_HIGH, }
            other_paramters_str = str(other_parameters_dict).replace("'", "''")

            insert_query = f"""INSERT INTO version (version_id, version_comment, consumer_categories, cable_cost_dict, connection_available_cables, other_parameters) VALUES
                ('{VERSION_ID}', '{VERSION_COMMENT}', '{consumer_categories_str}', '{cable_cost_dict_str}', '{connection_available_cables_str}', '{other_paramters_str}')"""
            self.cur.execute(insert_query)
            self.logger.info(f"Version: {VERSION_ID} (created for the first time)")

    def copy_postcode_result_table(self, plz: int) -> None:
        """
        Copies the given plz entry from postcode to the postcode_result table
        :param plz:
        :return:
        """
        query = """INSERT INTO postcode_result (version_id, postcode_result_plz, geom)
                   SELECT %(v)s as version_id, plz, geom
                   FROM postcode
                   WHERE plz = %(p)s
                   LIMIT 1
                   ON CONFLICT (version_id,postcode_result_plz) DO NOTHING;"""

        self.cur.execute(query, {"v": VERSION_ID, "p": plz})

    def set_residential_buildings_table(self, plz: int):
        """
        * Fills buildings_tem with residential buildings that lie inside the postal code geometry
        :param plz:
        :return:
        """

        # Fill table
        query = """INSERT INTO buildings_tem (osm_id, area, type, geom, center, floors)
                   SELECT osm_id, area, building_t, geom, ST_Centroid(geom), floors::int
                   FROM res
                   WHERE ST_Contains((SELECT post.geom
                                      FROM postcode_result as post
                                      WHERE version_id = %(v)s
                                        AND postcode_result_plz = %(plz)s
                                      LIMIT 1), ST_Centroid(res.geom));
        UPDATE buildings_tem
        SET plz = %(plz)s
        WHERE plz ISNULL;"""
        self.cur.execute(query, {"v": VERSION_ID, "plz": plz})

    def set_buildings_table(self, buildings_data: list[tuple]) -> None:
        """
        Insert buildings data associated with a specific postal code into the database.

        This function takes building data and inserts it into a temporary buildings table, associating each
        building with the given postal code. The temporary tables are then used when generating grids.

        Args:
            buildings_data (list[tuple[int, float, str, str, str, int, int]]): List of building tuples
                containing (id, floor_area, building_type, geom, center_geom, floor_number, households).

        Returns:
            None
        """
        insert_query = """
            INSERT INTO buildings_tem
            (osm_id, area, type, geom, center, floors, households_per_building, address_street_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cur.executemany(insert_query, buildings_data)

    def set_other_buildings_table(self, plz: int):
        """
        * Fills buildings_tem with other (non-residential) buildings inside the plz area
        * Sets all floors to 1 if missing
        :param plz:
        :return:
        """

        # Fill table
        query = """INSERT INTO buildings_tem(osm_id, area, type, geom, center)
                   SELECT osm_id, area, use, geom, ST_Centroid(geom)
                   FROM oth AS o
                   WHERE o.use in ('Commercial', 'Public')
                     AND ST_Contains((SELECT post.geom
                                      FROM postcode_result as post
                                      WHERE version_id = %(v)s
                                        AND postcode_result_plz = %(plz)s), ST_Centroid(o.geom));;
        UPDATE buildings_tem
        SET plz = %(plz)s
        WHERE plz ISNULL;
        UPDATE buildings_tem
        SET floors = 1
        WHERE floors ISNULL;"""
        self.cur.execute(query, {"v": VERSION_ID, "plz": plz})

    def remove_duplicate_buildings(self):
        """
        * Remove buildings without geometry or osm_id
        * Remove buildings that are duplicates (copy id) of others
        :return:
        """
        remove_query = """DELETE
                          FROM buildings_tem
                          WHERE geom ISNULL;"""
        self.cur.execute(remove_query)

        remove_noid_building = """DELETE
                                  FROM buildings_tem
                                  WHERE osm_id ISNULL;"""
        self.cur.execute(remove_noid_building)

        query = """DELETE
                   FROM buildings_tem
                   WHERE geom IN
                         (SELECT geom FROM buildings_tem GROUP BY geom HAVING count(*) > 1)
                     AND osm_id LIKE '%copy%';"""
        self.cur.execute(query)

    def compute_house_distance_metric(self, plz: int, sample_size: int = 50, k_nearest: int = 4) -> float:
        """Computes the average inter-building distance (meters) based on a random sample
        and writes house_distance into postcode_result. Returns the computed value.
        """
        distance_query = f"""WITH some_buildings AS (SELECT osm_id, center
                                                    FROM buildings_tem
                                                    ORDER BY RANDOM()
                                                    LIMIT {sample_size})
                            SELECT b.osm_id, d.dist
                            FROM some_buildings AS b
                                     LEFT JOIN LATERAL (
                                SELECT ST_Distance(b.center, b2.center) AS dist
                                FROM buildings_tem AS b2
                                WHERE b.osm_id <> b2.osm_id
                                ORDER BY b.center <-> b2.center
                                LIMIT {k_nearest}) AS d
                                               ON TRUE;"""
        self.cur.execute(distance_query)
        data = self.cur.fetchall()
        if not data:
            raise ValueError("No buildings in buildings_tem for house distance calculation.")
        distance_vals = [t[1] for t in data if t[1] is not None]
        if not distance_vals:
            raise ValueError("House distance calculation returned no distances.")
        avg_dis = float(sum(distance_vals) / len(distance_vals))
        update_query = """
            UPDATE postcode_result
            SET house_distance = %(avg)s
            WHERE version_id = %(v)s
              AND postcode_result_plz = %(p)s;"""
        self.cur.execute(update_query, {"avg": avg_dis, "v": VERSION_ID, "p": plz})
        return avg_dis

    def compute_avg_households_per_building(self, plz: int) -> float:
        """Computes the average number of households per (residential) building from buildings_tem
        and writes avg_households_per_building into postcode_result. Returns the value.
        """
        avg_query = """
            SELECT AVG(households_per_building)::DOUBLE PRECISION
            FROM buildings_tem
            WHERE households_per_building IS NOT NULL
              AND type IN ('SFH','TH','MFH','AB');"""
        self.cur.execute(avg_query, {"p": plz})
        avg_val = self.cur.fetchone()[0]
        if avg_val is None:
            raise ValueError(f"No residential buildings with household data for ZIP {plz}.")
        update_query = """
            UPDATE postcode_result
            SET avg_households_per_building = %(avg)s
            WHERE version_id = %(v)s
              AND postcode_result_plz = %(p)s;"""
        self.cur.execute(update_query, {"avg": avg_val, "v": VERSION_ID, "p": plz})
        return float(avg_val)

    def set_settlement_type_per_plz(
        self,
        plz: int,
        household_thresholds: dict | None = None,
        distance_thresholds: dict | None = None,
    ) -> int:
        """Determines settlement_type (1=rural, 2=semi-urban, 3=urban) using a weighted (continuous) combination
        of two metrics:
          - avg_households_per_building (higher => more urban)
          - house_distance (smaller => more urban)

        Method (weighted only):
          1. Normalize household metric to [0,1]:
               0 when avg <= rural_max ->rural, 1 when avg >= urban_min -> urban, linear in between
          2. Normalize distance to [0,1] (inverted):
               0 when distance >= suburban_max -> rural, 1 when distance <= urban_max ->urban, linear in between
          3. Score = 0.5 * hh_norm + 0.5 * dist_norm
          4. Discretize: Score < 1/3 -> 1, < 2/3 -> 2, else 3

        Parameters can be calibrated; defaults come from configuration.
        """
        if household_thresholds is None:
            household_thresholds = {"rural_max": RURAL_MAX_THRESHOLD, "urban_min": URBAN_MIN_THRESHOLD}
        if distance_thresholds is None:
            distance_thresholds = {"urban_max": 25.0, "suburban_max": 45.0}

        fetch_query = """
            SELECT avg_households_per_building, house_distance
            FROM postcode_result
            WHERE version_id = %(v)s AND postcode_result_plz = %(p)s;"""
        self.cur.execute(fetch_query, {"v": VERSION_ID, "p": plz})
        row = self.cur.fetchone()
        if not row or row[0] is None or row[1] is None:
            raise ValueError("Both metrics must be set before classification.")
        avg_households, house_distance = float(row[0]), float(row[1])

        # Normierung Haushalte
        denom_hh = max(1e-9, (household_thresholds["urban_min"] - household_thresholds["rural_max"]))
        hh_norm = (avg_households - household_thresholds["rural_max"]) / denom_hh
        hh_norm = min(1.0, max(0.0, hh_norm))
        # Normierung Distanz (invertiert)
        denom_dist = max(1e-9, (distance_thresholds["suburban_max"] - distance_thresholds["urban_max"]))
        dist_norm_raw = (house_distance - distance_thresholds["urban_max"]) / denom_dist
        dist_norm = 1.0 - min(1.0, max(0.0, dist_norm_raw))

        score = 0.5 * hh_norm + 0.5 * dist_norm
        if score >= 2/3:
            final_class = 3
        elif score >= 1/3:
            final_class = 2
        else:
            final_class = 1

        update_query = """
            UPDATE postcode_result
            SET settlement_type = %(stype)s
            WHERE version_id = %(v)s AND postcode_result_plz = %(p)s;"""
        self.cur.execute(update_query, {"stype": final_class, "v": VERSION_ID, "p": plz})
        return final_class

    def set_building_peak_load(self) -> int:
        """
        * Sets the area, type and peak_load in the buildings_tem table
        * Removes buildings with zero load from the buildings_tem table
        :return: Number of removed unloaded buildings from buildings_tem
        """
        query = """
                UPDATE buildings_tem
                SET area = ST_Area(geom);
                UPDATE buildings_tem
                
                -- Update households_per_building only if it has not been set already.
                -- For InfDB data this is already set.
                SET households_per_building = (
                    CASE
                    WHEN type IN ('TH', 'Commercial', 'Public', 'Industrial') THEN 1
                    WHEN type = 'SFH' AND area < 160 THEN 1
                    WHEN type = 'SFH' AND area >= 160 THEN 2
                    WHEN type IN ('MFH', 'AB') THEN floor(area / 50) * floors
                    ELSE 0
                    END
                )
                WHERE households_per_building IS NULL;
                
                UPDATE buildings_tem b
                SET peak_load_in_kw = (CASE
                                           WHEN b.type IN ('SFH', 'TH', 'MFH', 'AB') THEN b.households_per_building *
                                                                                          (SELECT peak_load FROM consumer_categories WHERE definition = b.type)
                                           WHEN b.type IN ('Commercial', 'Public', 'Industrial') THEN b.area *
                                                                                                      (SELECT peak_load_per_m2
                                                                                                       FROM consumer_categories
                                                                                                       WHERE definition = b.type) /
                                                                                                      1000
                                           ELSE 0
                    END);"""
        self.cur.execute(query)

        count_query = ("""SELECT COUNT(*)
                          FROM buildings_tem
                          WHERE peak_load_in_kw = 0;""")
        self.cur.execute(count_query)
        count = self.cur.fetchone()[0]

        delete_query = """DELETE
                          FROM buildings_tem
                          WHERE peak_load_in_kw = 0;"""
        self.cur.execute(delete_query)

        return count

    def update_too_large_consumers_to_zero(self) -> int:
        """
        Sets the load to zero if the peak load is too large (> 100)
        :return: number of the large customers
        """
        query = """
                UPDATE buildings_tem
                SET peak_load_in_kw = 0
                WHERE peak_load_in_kw > 100
                  AND type IN ('Commercial', 'Public');
                SELECT COUNT(*)
                FROM buildings_tem
                WHERE peak_load_in_kw = 0;"""
        self.cur.execute(query)
        too_large = self.cur.fetchone()[0]

        return too_large

    def assign_close_buildings(self) -> None:
        """
        * Set peak load to zero, if a building is too near or touching to a too large customer?
        :return:
        """
        while True:
            remove_query = """WITH close (un) AS (SELECT ST_Union(geom)
                                                  FROM buildings_tem
                                                  WHERE peak_load_in_kw = 0)
                              UPDATE buildings_tem b
                              SET peak_load_in_kw = 0
                              FROM close AS c
                              WHERE ST_Touches(b.geom, c.un)
                                AND b.type IN ('Commercial', 'Public', 'Industrial')
                                AND b.peak_load_in_kw != 0;"""
            self.cur.execute(remove_query)

            count_query = """WITH close (un) AS (SELECT ST_Union(geom)
                                                 FROM buildings_tem
                                                 WHERE peak_load_in_kw = 0)
                             SELECT COUNT(*)
                             FROM buildings_tem AS b,
                                  close AS c
                             WHERE ST_Touches(b.geom, c.un)
                               AND b.type IN ('Commercial', 'Public', 'Industrial')
                               AND b.peak_load_in_kw != 0;"""
            self.cur.execute(count_query)
            count = self.cur.fetchone()[0]
            if count == 0 or count is None:
                break

        return None

    def insert_transformers(self, plz: int) -> None:
        """
        Add up the existing transformers from transformers table to the buildings_tem table
        :param plz:
        :return:
        """
        insert_query = """
                       --UPDATE transformers SET geom = ST_Centroid(geom) WHERE ST_GeometryType(geom) =  'ST_Polygon';
                       INSERT INTO buildings_tem (osm_id, geom)--(osm_id,center)
                       SELECT osm_id, geom
                       --FROM transformers WHERE ST_Within(geom, (SELECT geom FROM postcode_result LIMIT 1)) IS FALSE;
                       FROM transformers as t
                       WHERE ST_Within(t.geom, (SELECT geom
                                                FROM postcode_result
                                                WHERE postcode_result_plz = %(p)s
                                                  AND version_id = %(v)s)); --IS FALSE;
                       UPDATE buildings_tem
                       SET plz = %(p)s
                       WHERE plz ISNULL;
                       UPDATE buildings_tem
                       SET center = ST_Centroid(geom)
                       WHERE center ISNULL;
                       UPDATE buildings_tem
                       SET type = 'Transformer'
                       WHERE type ISNULL;
                       UPDATE buildings_tem
                       SET peak_load_in_kw = -1
                       WHERE peak_load_in_kw ISNULL;"""
        self.cur.execute(insert_query, {"p": plz, "v": VERSION_ID})

    def count_indoor_transformers(self) -> None:
        """Counts indoor transformers before deleting them"""
        query = """WITH union_table (ungeom) AS
                                (SELECT ST_Union(geom) FROM buildings_tem WHERE peak_load_in_kw = 0)
                   SELECT COUNT(*)
                   FROM buildings_tem
                   WHERE ST_Within(center, (SELECT ungeom FROM union_table))
                     AND type = 'Transformer';"""
        self.cur.execute(query)
        count = self.cur.fetchone()[0]
        self.logger.debug(f"{count} indoor transformers will be deleted")

    def drop_indoor_transformers(self) -> None:
        """
        Drop transformer if it is inside a building with zero load
        :return:
        """
        query = """WITH union_table (ungeom) AS
                                (SELECT ST_Union(geom) FROM buildings_tem WHERE peak_load_in_kw = 0)
                   DELETE
                   FROM buildings_tem
                   WHERE ST_Within(center, (SELECT ungeom FROM union_table))
                     AND type = 'Transformer';"""
        self.cur.execute(query)   
    
    def set_ways_tem_table_infdb(self, ways_data: list[tuple]) -> int:
        """
        Insert remote ways into the local ways_tem table.

        Args:
            ways_data (list[tuple]): Each tuple should contain
                (clazz, source, target, cost, reverse_cost, geom, way_id)

        Returns:
            int: Number of inserted ways
        """
        if not ways_data:
            raise ValueError("No rows to insert into ways_tem")

        insert_query = """
            INSERT INTO ways_tem
            (clazz, source, target, cost, reverse_cost, geom, way_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        self.cur.executemany(insert_query, ways_data)

        self.cur.execute("SELECT COUNT(*) FROM ways_tem")
        return self.cur.fetchone()[0]



    def set_ways_tem_table(self, plz: int) -> int:
        """
        * Inserts ways inside the plz area to the ways_tem table
        :param plz:
        :return: number of ways in ways_tem
        """
        query = """INSERT INTO ways_tem
                   SELECT *
                   FROM ways AS w
                   WHERE ST_Intersects(w.geom, (SELECT geom
                                                FROM postcode_result
                                                WHERE version_id = %(v)s
                                                  AND postcode_result_plz = %(p)s));
        SELECT COUNT(*)
        FROM ways_tem;"""
        self.cur.execute(query, {"v": VERSION_ID, "p": plz})
        count = self.cur.fetchone()[0]

        if count == 0:
            raise ValueError(f"Ways table is empty for the given plz: {plz}")

        return count

    def preprocess_ways(self) -> None:
        """
        Runs the geometric preprocessing steps for the ways_tem table using two core functions:

        1. segment_intersecting_ways():
        - Detects where roads intersect geometrically.
        - Splits intersecting road segments into new segments at the intersection point.
        - Inserts the resulting segments into the working table `ways_tem`.
        - Internally uses: 
            - insert_way_segment() for adding new segments

        2. generate_building_to_way_connections():
        - Connects each building to the closest road segment.
        - For each building, generates a connection line to the corresponding way.
        - Splits the road segment at the connection point and updates `ways_tem`.
        - Uses:
            - generate_building_way_connection_candidates() for finding potential connections
            - insert_way_segment() for adding new segments
            - split_way_at_connection_points() for splitting ways at connection points

        These two functions are executed in sequence to ensure that:
        - All intersecting ways are properly split.
        - All buildings are connected to the network via dedicated segments.

        When the flag USE_INFDB is set to "True", the function generate_building_to_way_connections_infdb() 
        is used instead. This version utilizes the 'address_street_id' column in the infdb.buildings table, 
        which stores the closest road segment assigned via address-level matching. 
        If this column is null for a building, fallback to the traditional distance-based logic is applied.
        """
        self.cur.execute("SELECT segment_intersecting_ways();")

        if USE_INFDB:
            self.cur.execute("SELECT generate_building_to_way_connections_infdb();")
        else:
            self.cur.execute("SELECT generate_building_to_way_connections();")

    def build_pgr_network_topology(self, plz: int) -> None:
        """Builds the pgRouting-compatible network topology from the updated `ways_tem` table.
        This includes:
        1. pgr_createTopology():
        - Adds `source` and `target` node columns to `ways_tem`.
        - Assigns node IDs by analyzing the start and end points of each geometry.
        - Required to enable routing and graph operations on the road network.
        2. pgr_analyzeGraph():
        - Verifies the graph topology and reports disconnected components.
        - Ensures the routing network is clean and usable.
        """
        edge_table = f"ways_tem_{plz}"
        vertices_table = f"{edge_table}_vertices_pgr"
        # create topology on the PLZ-specific ways table
        self.cur.execute(
            # specify column names positionally to avoid version-specific errors
            f"SELECT pgr_createTopology('{edge_table}', 0.01, the_geom:='geom', id:='way_id', clean:=true);"
        )
        # analyze the resulting graph using the same PLZ-specific table
        self.cur.execute(
            f"SELECT pgr_analyzeGraph('{edge_table}', 0.01, the_geom:='geom');"
        )
        # Expose vertices table through a session-local view for easier downstream queries
        self.cur.execute(
            f"CREATE TEMP VIEW ways_tem_vertices_pgr AS SELECT * FROM {vertices_table}"
        )


    def update_ways_cost(self) -> None:
        """
        Calculates the length of each way and stores in ways_tem.cost as meter
        """
        query = """UPDATE ways_tem
                   SET cost = ST_Length(geom);
        UPDATE ways_tem
        SET reverse_cost = cost;"""
        self.cur.execute(query)

    def set_vertice_id(self) -> int:
        """
        Updates buildings_tem with the vertice_id s from ways_tem_vertices_pgr
        :return:
        """
        query = """UPDATE buildings_tem b
                   SET vertice_id = (SELECT id
                                     FROM ways_tem_vertices_pgr AS v
                                     WHERE ST_Equals(v.the_geom, b.center));"""
        self.cur.execute(query)

        query2 = """UPDATE buildings_tem b
                    SET connection_point = (SELECT target FROM ways_tem WHERE source = b.vertice_id LIMIT 1)
                    WHERE vertice_id IS NOT NULL
                      AND connection_point IS NULL;"""
        self.cur.execute(query2)

        count_query = """ SELECT COUNT(*)
                          FROM buildings_tem
                          WHERE connection_point IS NULL
                            AND peak_load_in_kw != 0;"""
        self.cur.execute(count_query)
        count = self.cur.fetchone()[0]

        delete_query = """DELETE
                          FROM buildings_tem
                          WHERE connection_point IS NULL
                            AND peak_load_in_kw != 0;"""
        self.cur.execute(delete_query)

        return count

    def get_ags_log(self) -> pd.DataFrame:
        """Get AGS log: the official municipal keys (Amtlicher Gemeindeschlüssel) of municipalities
        whose buildings have already been imported into the database.
        :return: table with column ags
        """
        query = """SELECT *
                   FROM ags_log;"""
        df_query = pd.read_sql_query(query, con=self.conn, )
        return df_query
