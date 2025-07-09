import psycopg2
import os
import logging
import time
from src.config_loader import *

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DB_NAME = INFDB_DBNAME
DB_USER = INFDB_USER
DB_HOST = INFDB_HOST  # Replace with database IP-address
DB_PORT = INFDB_PORT
DB_PASSWORD = INFDB_PASSWORD

# SQL files directory and list of files to execute in order
WAYS_SQL_DIR = os.path.join(os.path.dirname(__file__), 'ways_sql')
BUILDINGS_SQL_DIR = os.path.join(os.path.dirname(__file__), 'buildings_sql')


WAYS_SQL_FILES = [
    '00_cleanup.sql',
    '01_create_functions.sql',
    '02_create_ways_table.sql',
    '03_fill_id_ways_table.sql',
    '04_create_names_table.sql',
]
BUILDINGS_SQL_FILES = [
    '00_cleanup.sql',
    '01_create_functions.sql',
    '02_create_buildings_table.sql',
    '03_fill_id_object_id_building_use.sql',
    '04_fill_height.sql',
    '05_fill_floor_area_geom.sql',
    '06_create_touching_buildings_temp_tables.sql',
    '07_fill_floor_number.sql',
    '08_fill_occupants.sql',
    '09_fill_households.sql',
    '10_fill_construction_year.sql',
    '11_fill_building_type.sql',
    '12_assign_postcode_to_buildings.sql',
    '13_create_address_table.sql',
    '14_assign_streets_to_buildings.sql',
    '15_add_constraints.sql'
]


class PostgreSQLExecutor:
    def __init__(self, host, port, database, username, password):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.connection = None
        self.cursor = None

    def connect(self):
        """Establish database connection"""
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password
            )
            self.cursor = self.connection.cursor()
            logger.info(f"Successfully connected to PostgreSQL database at {self.host}:{self.port}")

        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise

    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logger.info("Database connection closed")

    def execute_sql_file(self, sql_dir, file_path):
        """Execute SQL commands from a file"""
        try:
            full_path = os.path.join(sql_dir, file_path)
            with open(full_path, 'r', encoding='utf-8') as file:
                sql_content = file.read()

            logger.info(f"Executing {os.path.join(sql_dir, file_path)}")
            self.cursor.execute(sql_content)
            self.connection.commit()
            logger.info(f"✅ Successfully executed {file_path}")

        except Exception as e:
            logger.error(f"❌ Error executing {file_path}: {str(e)}")
            self.connection.rollback()
            raise

    def execute_sql_scripts(self, sql_dir, script_files):
        """Execute multiple SQL script files in order"""
        try:
            self.connect()

            total_files = len(script_files)
            logger.info(f"Starting execution of {total_files} SQL scripts")

            for i, script_file in enumerate(script_files, 1):
                if not os.path.exists(os.path.join(sql_dir, script_file)):
                    msg = f"SQL file not found: {script_file}"
                    logger.error(msg)
                    raise FileNotFoundError(msg)

                logger.info(f"[{i}/{total_files}] Executing script: {script_file}")
                start_time = time.time()
                self.execute_sql_file(sql_dir, script_file)
                logger.info(f"[{i}/{total_files}] Finished script: in {round(time.time() - start_time, 2)} seconds")

                # Small delay between scripts
                if i < total_files:
                    time.sleep(0.5)

            logger.info("🎉 All SQL scripts executed successfully!")

        except Exception as e:
            logger.error(f"💥 Error during script execution: {str(e)}")
            raise
        finally:
            self.disconnect()


def main():
    try:
        # Initialize database executor
        db_executor = PostgreSQLExecutor(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            username=DB_USER,
            password=DB_PASSWORD
        )

        # Validate all SQL files exist before starting
        missing_ways = [f for f in WAYS_SQL_FILES if not os.path.exists(os.path.join(WAYS_SQL_DIR, f))]
        missing_buildings = [f for f in BUILDINGS_SQL_FILES if not os.path.exists(os.path.join(BUILDINGS_SQL_DIR, f))]

        if missing_ways or missing_buildings:
            if missing_ways:
                logger.error(f"Missing WAYS SQL files in {WAYS_SQL_DIR}/: {missing_ways}")
            if missing_buildings:
                logger.error(f"Missing BUILDINGS SQL files in {BUILDINGS_SQL_DIR}/: {missing_buildings}")
            return 1

        
        # Execute WAYS scripts first
        logger.info("Running WAYS SQL scripts")
        db_executor.execute_sql_scripts(WAYS_SQL_DIR, WAYS_SQL_FILES)

        # Then BUILDINGS scripts
        logger.info("Running BUILDINGS SQL scripts")
        db_executor.execute_sql_scripts(BUILDINGS_SQL_DIR, BUILDINGS_SQL_FILES)

        print("🏠 Prepared buildings table successfully!")
        return 0

    except Exception as e:
        print(f"❌ Preparation of buildings failed: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())