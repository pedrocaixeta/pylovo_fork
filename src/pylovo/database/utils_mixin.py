import warnings
import sys
from pathlib import Path
from abc import ABC

# Import table structure from config directory
# Add config directory to path to import config_table_structure
config_dir = Path(__file__).parent.parent.parent.parent / "config"
if str(config_dir) not in sys.path:
    sys.path.insert(0, str(config_dir))

from config_table_structure import *

from pylovo.config_loader import *
from pylovo.database.base_mixin import BaseMixin

import pandas as pd

warnings.simplefilter(action='ignore', category=UserWarning)


class UtilsMixin(BaseMixin, ABC):
    def __init__(self):
        super().__init__()

    def __del__(self):
        self.cur.close()
        self.conn.close()

    def create_temp_tables(self, plz: int) -> None:
        """Create PLZ-suffixed temporary tables and session-local views."""
        self.drop_temp_tables(plz)
        for base_name, query in TEMP_CREATE_QUERIES.items():
            table_name = f"{base_name}_{plz}"
            # create a dedicated table for each PLZ
            self.cur.execute(query.replace(base_name, table_name))
            # expose a session-local view with the common name
            self.cur.execute(f"CREATE TEMP VIEW {base_name} AS SELECT * FROM {table_name}")
            # self.cur.execute(f"CREATE OR REPLACE VIEW {base_name} AS SELECT * FROM {table_name}") #only for debugging

    def drop_temp_tables(self, plz: int) -> None:
        """Drop PLZ-suffixed tables and their views."""
        for base_name in TEMP_CREATE_QUERIES.keys():
            self.cur.execute(f"DROP VIEW IF EXISTS {base_name} CASCADE")
            self.cur.execute(f"DROP TABLE IF EXISTS {base_name}_{plz} CASCADE")
        self.cur.execute("DROP VIEW IF EXISTS ways_tem_vertices_pgr CASCADE")
        # Drop the vertices table created by pgr_createTopology (correct naming pattern)
        self.cur.execute(f"DROP TABLE IF EXISTS ways_tem_{plz}_vertices_pgr CASCADE")

    def refresh_materialized_views(self) -> None:
        for query in REFRESH_QUERIES.values():
            self.cur.execute(query)

    def commit_changes(self):
        self.conn.commit()

    def get_list_from_plz(self, plz: int) -> list:
        query = """SELECT DISTINCT kcid, bcid
                   FROM grid_result
                   WHERE version_id = %(v)s
                     AND plz = %(p)s
                   ORDER BY kcid, bcid;"""
        self.cur.execute(query, {"p": plz, "v": VERSION_ID})
        cluster_list = self.cur.fetchall()

        return cluster_list

    def delete_transformers_from_buildings_tem(self, vertices: list) -> None:
        """
        Deletes selected transformers from buildings_tem
        :param vertices:
        :return:
        """
        query = """
                DELETE
                FROM buildings_tem
                WHERE vertice_id IN %(v)s;"""
        self.cur.execute(query, {"v": tuple(map(int, vertices))})

    def get_consumer_categories(self):
        """
        Returns: A dataframe with self-defined consumer categories and typical values
        """
        query = """SELECT *
                   FROM consumer_categories"""
        cc_df = pd.read_sql_query(query, self.conn)
        cc_df.set_index("definition", drop=False, inplace=True)
        cc_df.sort_index(inplace=True)
        self.logger.debug("Consumer categories fetched.")
        return cc_df

    def get_municipal_register(self) -> pd.DataFrame:
        """Return the complete municipal register as a DataFrame."""
        query = """SELECT *
                   FROM municipal_register;"""
        self.cur.execute(query)
        register = self.cur.fetchall()
        return pd.DataFrame(register, columns=MUNICIPAL_REGISTER)

    def get_municipal_register_for_plz(self, plz: int) -> pd.DataFrame:
        """Return municipal register rows for a single PLZ."""
        query = """SELECT *
                   FROM municipal_register
                   WHERE plz = %(p)s;"""
        self.cur.execute(query, {"p": int(plz)})
        register = self.cur.fetchall()
        return pd.DataFrame(register, columns=MUNICIPAL_REGISTER)
