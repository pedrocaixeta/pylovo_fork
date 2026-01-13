from typing import Any

import psycopg2 as psy

from src import utils
from pylovo.config_loader import *
from pylovo.database.database_client import DatabaseClient


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
                options=f"-c search_path={INFDB_SOURCE_SCHEMA},public",
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

    def fetch_buildings_from_infdb(self, plz: int) -> list[tuple]:
        """
        Retrieve all buildings whose centroids are contained within a specified postcode (PLZ).
        In testing mode, filters buildings to only those within the testing geometry.

        Args:
            plz (str): The plz of the buildings to get

        Returns:
            list[tuple]: A list of tuples, where each tuple contains:
                - id (int): Unique building identifier
                - floor_area (float): Floor area of the building in square meters
                - building_type (str): Type of building (e.g., 'SFH' for Single Family House)
                - geom (str): Building geometry in PostGIS EWKB format as hex string
                - center (str): Building centroid geometry in PostGIS EWKB format as hex string
                - floor_number (int): Number of floors in the building
                - households (int): Number of households in the building
                - address_street_id (int): id of the way that the building is connected to
                - construction_year (str): Year the building was constructed
        """
        query = """
            SELECT id, floor_area, COALESCE(building_type, building_use) as type,
                   geom, ST_Centroid(geom) as center, floor_number, households, address_street_id, construction_year
            FROM basedata.buildings
            WHERE postcode = %(p)s
            AND building_use IN ('Commercial', 'Public', 'Residential')
        """
        self.cur.execute(query, {"p": plz})
        buildings = self.cur.fetchall()

        return buildings
    
    def fetch_ways_from_infdb(self, plz) -> list:
        """
        Fetch ways from remote DB for a given postcode.
        Filter out clazz:72 (Rad- und Fußweg)
        In testing mode, fetches ways from allocated_plz (geometry filtering handled locally).
        """
        query = """
            SELECT clazz, source, target, cost, reverse_cost, geom, way_id
            FROM ways
            WHERE postcode = %(plz)s and clazz != 72
        """
        self.cur.execute(query, {"plz": plz})

        ways = self.cur.fetchall()
        if not ways:
            raise ValueError("No ways found in remote DB intersecting the given PLZ geometry")

        return ways
    
    def fetch_postcode_from_infb(self) -> list[tuple]:
        """
        Fetch postcode data from opendata schema and return rows matching the local schema.
        Returns tuples of (plz, note, qkm, population, geom) from INFDB_SOURCE_SCHEMA.
        """
        query = """
            SELECT plz, note, qkm, einwohner, geom
            FROM opendata.postcodes_germany
            ORDER BY plz;
        """
        self.cur.execute(query)
        rows = self.cur.fetchall()
        if not rows:
            raise ValueError("No postcode found in infdb")

        return rows

