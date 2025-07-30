"""
This script creates a src database and fills with raw data from referenced files.
Do not use DatabaseConstructor class unless you want to create a new database.
"""

from raw_data.municipal_register.join_regiostar_gemeindeverz import create_municipal_register
from src.database.database_constructor import DatabaseConstructor
from src import utils
from src.config_loader import *


logger = utils.create_logger(name="main_constructor", log_file="log.txt", log_level=LOG_LEVEL)


def main():
    ### Create constructor class
    sgc = DatabaseConstructor()

    ### Create database with predefined table structure
    logger.info("### CREATE ALL TABLES ###")
    sgc.create_table(table_name="all")

    ### Add transformer data from geojson to the database
    logger.info("### QUERY TRANSFORMERS AND INSERT THEM INTO DB (~50 min if processing new trafo data) ###")
    sgc.transformers_to_db()

    if USE_INFDB:
        ### Here atm only equipment_data are imported as postcodes are imported from infdb but keep this for modularity
        logger.info("### POPULATE DB WITH EQUIPMENT DATA ###")
        sgc.csv_to_db(CSV_FILE_LIST_INFDB)

    if not USE_INFDB:
        ### Add defined csv raw data from CSV_FILE_LIST to the database
        logger.info("### POPULATE DB WITH CSV RAW DATA ###")
        sgc.csv_to_db(CSV_FILE_LIST)

        ### Create table with data from osm
        logger.info("### POPULATE public_2po_4pgr TABLE (~30 min) ###")
        sgc.create_public_2po_table()

        ### Transform these data into our ways table
        logger.info("### PROCESS WAYS AND INSERTING THEM INTO ways TABLE ###")
        sgc.ways_to_db()

   # Load PostGIS SQL functions required for preprocessing ways
    logger.info("### LOAD POSTGIS FUNCTIONS FOR WAYS PREPROCESSING ###")
    sgc.load_ways_preprocessing_functions()

    ### Create table with entries of all German municipalities and cities
    logger.info("### FILL municipal_register TABLE ###")
    create_municipal_register()

    logger.info("### DONE ###")


if __name__ == "__main__":
    main()