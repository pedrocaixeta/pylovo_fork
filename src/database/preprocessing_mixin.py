import json
import warnings
from abc import ABC
import pandas as pd

from src.config_loader import *
from src.database.base_mixin import BaseMixin

warnings.simplefilter(action='ignore', category=UserWarning)


class PreprocessingMixin(BaseMixin, ABC):
    def __init__(self):
        super().__init__()

    def insert_version_if_not_exists(self):
        count_query = f"""SELECT COUNT(*) 
            FROM version 
            WHERE "version_id" = '{VERSION_ID}'"""
        self.cur.execute(count_query)
        version_exists = self.cur.fetchone()[0]
        if not version_exists:
            consumer_categories_str = CONSUMER_CATEGORIES.to_json().replace("'", "''")
            connection_available_cables_str = str(CONSUMER_CONNECTION_AVAILABLE_CABLES).replace("'", "''")
            other_parameters_dict = {"LARGE_COMPONENT_LOWER_BOUND": LARGE_COMPONENT_LOWER_BOUND,
                                     "LARGE_COMPONENT_DIVIDER": LARGE_COMPONENT_DIVIDER, "VN": VN,
                                     "V_BAND_LOW": V_BAND_LOW, "V_BAND_HIGH": V_BAND_HIGH, }
            other_paramters_str = str(other_parameters_dict).replace("'", "''")

            insert_query = f"""INSERT INTO version (version_id, version_comment, consumer_categories, connection_available_cables, other_parameters) VALUES
                ('{VERSION_ID}', '{VERSION_COMMENT}', '{consumer_categories_str}', '{connection_available_cables_str}', '{other_paramters_str}')"""
            self.cur.execute(insert_query)
            self.logger.info(f"Version: {VERSION_ID} (created for the first time)")

    def insert_equipment_data_from_config(self, equipment_data: pd.DataFrame):
        """Populate equipment_data table from EQUIPMENT_DATA DataFrame defined in the version config.
        Replaces former pandas.to_sql variant (replace) with conflict-safe inserts.
        Reasons:
        Strategy:
        - Map columns to expected structure
        - Fill missing columns with None
        - Cast values (numeric fields to Int, missing -> None)
        - ON CONFLICT (version_id, name) DO UPDATE for idempotency / update
        """
        df = equipment_data.copy()
        expected_cols = ["version_id", "name", "s_max_kva", "max_i_a", "r_mohm_per_km", "x_mohm_per_km",
                         "z_mohm_per_km", "cost_eur", "typ", "application_area"]
        if "version_id" not in df.columns:
            df["version_id"] = VERSION_ID

        # Add any missing columns
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None
        
        # For cables, application_area is not needed - set to None
        if 'typ' in df.columns:
            df.loc[df['typ'] == 'Cable', 'application_area'] = None

        # Keep only relevant columns
        df = df[expected_cols]

        # Numeric conversion (Int / None)
        int_cols = ["s_max_kva", "max_i_a", "r_mohm_per_km", "x_mohm_per_km", "z_mohm_per_km", "cost_eur",
                    "application_area"]
        for c in int_cols:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')

        # Replace NaNs with None
        df = df.where(~df.isna(), None)

        insert_sql = ("""
                      INSERT INTO equipment_data
                      (version_id, name, s_max_kva, max_i_a, r_mohm_per_km, x_mohm_per_km, z_mohm_per_km, cost_eur, typ,
                       application_area)
                      VALUES (%(version_id)s, %(name)s, %(s_max_kva)s, %(max_i_a)s, %(r_mohm_per_km)s,
                              %(x_mohm_per_km)s, %(z_mohm_per_km)s, %(cost_eur)s, %(typ)s, %(application_area)s)
                      ON CONFLICT (version_id, name) DO UPDATE SET s_max_kva        = EXCLUDED.s_max_kva,
                                                                   max_i_a          = EXCLUDED.max_i_a,
                                                                   r_mohm_per_km    = EXCLUDED.r_mohm_per_km,
                                                                   x_mohm_per_km    = EXCLUDED.x_mohm_per_km,
                                                                   z_mohm_per_km    = EXCLUDED.z_mohm_per_km,
                                                                   cost_eur         = EXCLUDED.cost_eur,
                                                                   typ              = EXCLUDED.typ,
                                                                   application_area = EXCLUDED.application_area;""")
        rows = df.to_dict(orient='records')
        self.cur.executemany(insert_sql, rows)
        self.logger.info(f"Inserted/updated equipment_data rows: {len(rows)} (version {VERSION_ID})")

    def insert_consumer_categories_from_config(self, consumer_categories: pd.DataFrame):
        """Insert consumer_categories from config.
        Replaces pandas.to_sql(replace) with ON CONFLICT upserts for stable parallel execution.
        Table is global (no version_id). Existing IDs / definitions are updated.
        """
        df = consumer_categories.copy()

        if 'peak_load' in df.columns:
            s = df['peak_load']
            mask = s == 'PEAK_LOAD_HOUSEHOLD'
            if mask.any():
                # Explicitly assign numeric constant instead of using .replace to prevent FutureWarning
                s = s.where(~mask, PEAK_LOAD_HOUSEHOLD)
            df['peak_load'] = s

        # Expected target table columns
        expected_cols = ["consumer_category_id", "definition", "peak_load", "yearly_consumption", "peak_load_per_m2",
                         "yearly_consumption_per_m2", "sim_factor"]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None
        df = df[expected_cols]

        # Convert numeric columns
        numeric_cols = ['peak_load', 'yearly_consumption', 'peak_load_per_m2', 'yearly_consumption_per_m2',
                        'sim_factor']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.where(pd.notna(df), None)

        upsert_sql = ("""
                      INSERT INTO consumer_categories
                      (consumer_category_id, definition, peak_load, yearly_consumption, peak_load_per_m2,
                       yearly_consumption_per_m2, sim_factor)
                      VALUES (%(consumer_category_id)s, %(definition)s, %(peak_load)s, %(yearly_consumption)s,
                              %(peak_load_per_m2)s, %(yearly_consumption_per_m2)s, %(sim_factor)s)
                      ON CONFLICT (consumer_category_id) DO UPDATE SET definition                = EXCLUDED.definition,
                                                                       peak_load                 = EXCLUDED.peak_load,
                                                                       yearly_consumption        = EXCLUDED.yearly_consumption,
                                                                       peak_load_per_m2          = EXCLUDED.peak_load_per_m2,
                                                                       yearly_consumption_per_m2 = EXCLUDED.yearly_consumption_per_m2,
                                                                       sim_factor                = EXCLUDED.sim_factor;""")
        rows = df.to_dict(orient='records')
        self.cur.executemany(upsert_sql, rows)
        self.logger.info(f"Inserted/updated consumer_categories rows: {len(rows)}")

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

    def set_buildings_table(self, buildings_data: list[tuple], plz: int = None) -> None:
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
        if TESTING and plz is not None:
            # In testing mode, filter buildings by testing geometry
            self._set_buildings_table_with_geometry_filter(buildings_data, plz)
        else:
            # Normal mode - insert all buildings with processed construction_year
            processed_data = []
            for building in buildings_data:
                # Extract construction_year - take the first year if it's a range
                construction_year = building[8] if len(building) > 8 else None
                if construction_year and isinstance(construction_year, str) and '-' in construction_year:
                    try:
                        construction_year = int(construction_year.split('-')[0])
                    except (ValueError, IndexError):
                        construction_year = None
                elif construction_year:
                    try:
                        construction_year = int(construction_year)
                    except (ValueError, TypeError):
                        construction_year = None
                else:
                    construction_year = None
                
                # Create new tuple with processed construction_year
                processed_building = building[:8] + (construction_year,)
                processed_data.append(processed_building)
            
            insert_query = """
                INSERT INTO buildings_tem
                (osm_id, area, type, geom, center, floors, households_per_building, address_street_id, construction_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            self.cur.executemany(insert_query, processed_data)

    def _set_buildings_table_with_geometry_filter(self, buildings_data: list[tuple], plz: int) -> None:
        """
        Insert buildings data with geometry filtering for testing mode.
        Only buildings that intersect with the testing geometry are inserted.
        """
        if not buildings_data:
            return
            
        # Create a temporary table to hold the building data
        temp_table_query = """
            CREATE TEMP TABLE testing_buildings (
                osm_id integer,
                area double precision,
                type varchar,
                geom geometry,
                center geometry,
                floors integer,
                households_per_building integer,
                address_street_id integer,
                construction_year integer
            )
        """
        self.cur.execute(temp_table_query)
        
        # Process building data to handle construction_year ranges
        processed_data = []
        for building in buildings_data:
            # Extract construction_year - take the first year if it's a range
            construction_year = building[8] if len(building) > 8 else None
            if construction_year and isinstance(construction_year, str) and '-' in construction_year:
                try:
                    construction_year = int(construction_year.split('-')[0])
                except (ValueError, IndexError):
                    construction_year = None
            elif construction_year:
                try:
                    construction_year = int(construction_year)
                except (ValueError, TypeError):
                    construction_year = None
            else:
                construction_year = None
            
            # Create new tuple with processed construction_year
            processed_building = building[:8] + (construction_year,)
            processed_data.append(processed_building)
        
        # Insert all building data into temp table
        insert_query = """
            INSERT INTO testing_buildings
            (osm_id, area, type, geom, center, floors, households_per_building, address_street_id, construction_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cur.executemany(insert_query, processed_data)
        
        # Filter and insert only buildings that intersect with testing geometry
        filter_query = """
            INSERT INTO buildings_tem
            (osm_id, area, type, geom, center, floors, households_per_building, address_street_id, construction_year)
            SELECT tb.osm_id, tb.area, tb.type, tb.geom, tb.center, tb.floors, 
                   tb.households_per_building, tb.address_street_id, tb.construction_year
            FROM testing_buildings tb
            CROSS JOIN postcode p
            WHERE p.plz = %(plz)s
            AND p.testing_plz IS NOT NULL
            AND ST_Intersects(tb.geom, p.geom)
        """
        self.cur.execute(filter_query, {"plz": plz})
        
        # Drop temp table
        self.cur.execute("DROP TABLE testing_buildings")

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

    def calculate_house_distance_metric(self, plz: int, sample_size: int = 50, k_nearest: int = 4) -> float:
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

    def calculate_avg_households_per_building(self, plz: int) -> float:
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
        settlement_type_thresholds: dict | None = None,
    ) -> int:
        """Determines settlement_type (1=rural, 2=semi-urban, 3=urban) using a weighted (continuous) combination
        of two metrics:
          - avg_households_per_building (higher => more urban)
          - house_distance (smaller => more urban)

        Method (weighted only):
          1. Normalize household metric to [0,1]:
               0 when avg <= rural_max_households -> rural, 1 when avg >= urban_min_households -> urban, linear in between
          2. Normalize distance to [0,1] (inverted):
               0 when distance >= rural_min_distance -> rural, 1 when distance <= urban_max_distance -> urban, linear in between
          3. Score = 0.5 * hh_norm + 0.5 * dist_norm
          4. Discretize: Score < 1/3 -> 1, < 2/3 -> 2, else 3

        Parameters can be calibrated; defaults come from configuration.
        """
        fetch_query = """
            SELECT avg_households_per_building, house_distance
            FROM postcode_result
            WHERE version_id = %(v)s AND postcode_result_plz = %(p)s;"""
        self.cur.execute(fetch_query, {"v": VERSION_ID, "p": plz})
        row = self.cur.fetchone()
        if not row or row[0] is None or row[1] is None:
            raise ValueError("Both metrics must be set before classification.")
        avg_households, house_distance = float(row[0]), float(row[1])

        # Normalization households
        denom_hh = max(1e-9, (settlement_type_thresholds["urban_min_households"] - settlement_type_thresholds["rural_max_households"]))
        hh_norm = (avg_households - settlement_type_thresholds["rural_max_households"]) / denom_hh
        hh_norm = min(1.0, max(0.0, hh_norm))
        # Normalization distances (inverted)
        denom_dist = max(1e-9, (settlement_type_thresholds["rural_min_distance"] - settlement_type_thresholds["urban_max_distance"]))
        dist_norm_raw = (house_distance - settlement_type_thresholds["urban_max_distance"]) / denom_dist
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

    def set_ways_tem_table_infdb(self, ways_data: list[tuple], plz: int = None) -> int:
        """
        Insert remote ways into the local ways_tem table.

        Args:
            ways_data (list[tuple]): Each tuple should contain
                (clazz, source, target, cost, reverse_cost, geom, way_id)
            plz (int): PLZ for geometry filtering in testing mode

        Returns:
            int: Number of inserted ways
        """
        if not ways_data:
            raise ValueError("No rows to insert into ways_tem")

        if TESTING and plz is not None:
            # In testing mode, filter ways by testing geometry
            return self._set_ways_tem_table_with_geometry_filter(ways_data, plz)
        else:
            # Normal mode - insert all ways
            insert_query = """
                INSERT INTO ways_tem
                (clazz, source, target, cost, reverse_cost, geom, way_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            self.cur.executemany(insert_query, ways_data)
            self.cur.execute("SELECT COUNT(*) FROM ways_tem")
            return self.cur.fetchone()[0]

    def _set_ways_tem_table_with_geometry_filter(self, ways_data: list[tuple], plz: int) -> int:
        """
        Insert ways data with geometry filtering for testing mode.
        Only ways that intersect with the testing geometry are inserted.
        """
        if not ways_data:
            return 0
            
        # Create a temporary table to hold the ways data
        temp_table_query = """
            CREATE TEMP TABLE temp_ways (
                clazz integer,
                source integer,
                target integer,
                cost double precision,
                reverse_cost double precision,
                geom geometry,
                way_id integer
            )
        """
        self.cur.execute(temp_table_query)
        
        # Insert all ways data into temp table
        insert_query = """
            INSERT INTO temp_ways
            (clazz, source, target, cost, reverse_cost, geom, way_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        self.cur.executemany(insert_query, ways_data)
        
        # Filter and insert only ways that intersect with testing geometry
        filter_query = """
            INSERT INTO ways_tem
            (clazz, source, target, cost, reverse_cost, geom, way_id)
            SELECT tw.clazz, tw.source, tw.target, tw.cost, tw.reverse_cost, tw.geom, tw.way_id
            FROM temp_ways tw
            CROSS JOIN postcode p
            WHERE p.plz = %(plz)s
            AND p.testing_plz IS NOT NULL
            AND ST_Intersects(tw.geom, p.geom)
        """
        self.cur.execute(filter_query, {"plz": plz})
        
        # Get count of inserted ways
        self.cur.execute("SELECT COUNT(*) FROM ways_tem")
        count = self.cur.fetchone()[0]
        
        # Drop temp table
        self.cur.execute("DROP TABLE temp_ways")
        
        return count

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

    def insert_equipment_data(self, equipment_df: pd.DataFrame):
        """Insert equipment_data rows for current VERSION_ID if not already present for this version."""
        self.cur.execute("SELECT 1 FROM equipment_data WHERE version_id = %s LIMIT 1", (VERSION_ID,))
        if self.cur.fetchone():
            return

        required_cols = ['name', 'typ', 'application_area']
        for rc in required_cols:
            if rc not in equipment_df.columns:
                raise ValueError(f"Missing required equipment column: {rc}")

        # Ensure numeric coercion for optional integer fields
        int_cols = ['s_max_kva', 'max_i_a', 'r_mohm_per_km', 'x_mohm_per_km',
                    'z_mohm_per_km', 'cost_eur', 'application_area']
        for col in int_cols:
            if col in equipment_df.columns:
                equipment_df[col] = pd.to_numeric(equipment_df[col], errors='coerce').astype('Int64')

        equipment_df = equipment_df.where(~equipment_df.isna(), None)

        insert_sql = """
            INSERT INTO equipment_data
            (version_id, name, s_max_kva, max_i_a, r_mohm_per_km, x_mohm_per_km,
             z_mohm_per_km, cost_eur, typ, application_area)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        rows = []
        for _, r in equipment_df.iterrows():
            rows.append((
                VERSION_ID,
                r.get('name'),
                r.get('s_max_kva'),
                r.get('max_i_a'),
                r.get('r_mohm_per_km'),
                r.get('x_mohm_per_km'),
                r.get('z_mohm_per_km'),
                r.get('cost_eur'),
                r.get('typ'),
                r.get('application_area'),
            ))
        self.cur.executemany(insert_sql, rows)
        self.logger.debug("Inserted equipment_data for version %s", VERSION_ID)

    def get_testing_plz(self, plz: int) -> int:
        """Return mapped testing_plz if TESTING mode provides one, else original plz."""
        self.cur.execute("SELECT testing_plz FROM postcode WHERE plz = %(p)s LIMIT 1;", {"p": plz})
        row = self.cur.fetchone()
        if row and row[0]:
            return int(row[0])
        return plz
