import psycopg2
import os
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DB_HOST = 'ip'  # Replace with database IP-address
DB_PORT = 5432
DB_NAME = 'name'
DB_USER = 'user'
DB_PASSWORD = 'pw'

# SQL files directory and list of files to execute in order
SQL_DIR = 'buildings_sql'
SQL_FILES = [
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
    '12_add_constraints.sql'
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

    def execute_sql_file(self, file_path):
        """Execute SQL commands from a file"""
        try:
            full_path = os.path.join(SQL_DIR, file_path)
            with open(full_path, 'r', encoding='utf-8') as file:
                sql_content = file.read()

            logger.info(f"Executing {file_path}")
            self.cursor.execute(sql_content)
            self.connection.commit()
            logger.info(f"✅ Successfully executed {file_path}")

        except Exception as e:
            logger.error(f"❌ Error executing {file_path}: {str(e)}")
            self.connection.rollback()
            raise

    def execute_sql_scripts(self, script_files):
        """Execute multiple SQL script files in order"""
        try:
            self.connect()

            total_files = len(script_files)
            logger.info(f"Starting execution of {total_files} SQL scripts")

            for i, script_file in enumerate(script_files, 1):
                if not os.path.exists(os.path.join(SQL_DIR, script_file)):
                    msg = f"SQL file not found: {script_file}"
                    logger.error(msg)
                    raise FileNotFoundError(msg)

                logger.info(f"[{i}/{total_files}] Executing script: {script_file}")
                start_time = time.time()
                self.execute_sql_file(script_file)
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
        missing_files = [f for f in SQL_FILES if not os.path.exists(os.path.join(SQL_DIR, f))]
        if missing_files:
            logger.error(f"Missing SQL files in {SQL_DIR}/: {missing_files}")
            return 1

        # Execute all SQL scripts
        db_executor.execute_sql_scripts(SQL_FILES)

        print("🏠 Prepared buildings table successfully!")
        return 0

    except Exception as e:
        print(f"❌ Preparation of buildings failed: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())