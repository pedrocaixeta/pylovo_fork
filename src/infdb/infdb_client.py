import psycopg2 as psy

from src import utils
from src.config_loader import *


class InfdbClient:
    """Responsible for connecting to InfDB database."""

    def __init__(self, dbname=INFDB_DBNAME, user=INFDB_USER, pw=INFDB_PASSWORD, host=INFDB_HOST, port=INFDB_PORT, **kwargs):
        self.logger = utils.create_logger(
            "DatabaseClient", log_file=kwargs.get("log_file", "../log.txt"), log_level=LOG_LEVEL
        )
        try:
            self.conn = psy.connect(
                database=dbname,
                user=user,
                password=pw,
                host=host,
                port=port,
                options=f"-c search_path={TARGET_SCHEMA},public",
            )
            self.cur = self.conn.cursor()
            self.db_path = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{dbname}"
        except psy.OperationalError as err:
            self.logger.warning(f"Connecting to {dbname} was not successful."
                                f"Make sure, that you have established the SSH connection with correct port mapping.")
            raise err

        self.logger.debug(f"InfDB DatabaseClient is constructed and connected to {self.db_path}.")

    def __del__(self):
        self.cur.close()
        self.conn.close()

    def get_relevant_buildings_in_area(self, area_geom: str) -> list[tuple[int, float, str, str, str, int]]:
        """
        Retrieve all buildings whose centroids are contained within a specified area geometry.

        Args:
            area_geom (str): The area geometry which defines the boundary
                             within which to search for buildings.

        Returns:
            list[tuple[int, float, str, str, str, int]]: A list of tuples, where each tuple contains:
                - id (int): Unique building identifier
                - floor_area (float): Floor area of the building in square meters
                - building_type (str): Type of building (e.g., 'SFH' for Single Family House)
                - geom (str): Building geometry in PostGIS EWKB format as hex string
                - center (str): Building centroid geometry in PostGIS EWKB format as hex string
                - floor_number (int): Number of floors in the building
        """

        query = """
            SELECT id, floor_area, COALESCE(building_type, building_use) as type,
                   geom, ST_Centroid(geom) as center, floor_number
            FROM pylovo_input.buildings
            WHERE ST_Contains(%(area)s, ST_Centroid(geom))
            AND building_use IN ('Commertial', 'Public', 'Residential')
        """
        self.cur.execute(query, {"area": area_geom})
        result = self.cur.fetchall()

        assert (type(result) == list[tuple[int, float, str, str, str, int]])
        result = list[tuple[int, float, str, str, str, int]](self.cur.fetchall())

        return result