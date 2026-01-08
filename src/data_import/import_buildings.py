import glob

from src.database.database_constructor import DatabaseConstructor
from src.config_loader import *
from src.data_import.region_resolver import resolve_regions


def import_buildings_for_single_plz(gg):
    """
    Imports ags building data to the database for a given PLZ specified in the GridGenerator object.
    AGS is added to ags_log table to avoid importing the same building data again.

    :param gg: Grid generator object for querying relevant PLZ and AGS data
    """
    dbc_client = gg.dbc
    _, df_plz_ags = resolve_regions(dbc_client, plz=int(gg.plz))

    # Extract name and AGS for the desired PLZ (PLZ might map to multiple AGS)
    gg.logger.info(
        f"LV grids will be generated for PLZ {int(gg.plz)} - {len(df_plz_ags)} municipal register entries"
    )
    ags_list = sorted(set(df_plz_ags["ags"].tolist()))
    gg.logger.info(f"AGS to import: {ags_list}")

    # Check if AGS is already in the database (avoid duplication)
    df_log = dbc_client.get_ags_log()
    already_imported = set(df_log["ags"].values.tolist())
    ags_to_import = [a for a in ags_list if a not in already_imported]
    if not ags_to_import:
        gg.logger.info("Buildings for these AGS are already in the src database.")
        return
    gg.logger.info(f"Buildings for these AGS are not in the database and will be added: {ags_to_import}")

    # Define the path for building shapefiles
    data_path = os.path.abspath(os.path.join(PROJECT_ROOT, "raw_data", "buildings"))
    shapefiles_pattern = os.path.join(data_path, "*.shp")  # Pattern for shapefiles

    # Retrieve all matching shapefiles
    files_list = glob.glob(shapefiles_pattern, recursive=True)

    # Filter files containing any AGS in their filenames
    files_to_add = [file for file in files_list if any(str(a) in file for a in ags_to_import)]

    # Handle cases where no matching files are found
    if not files_to_add:
        raise FileNotFoundError(f"No shapefiles found for AGS {ags_to_import} in {data_path}")

    # Create a list of dictionaries for ogr_to_db()
    ogr_ls_dict = create_list_of_shp_files(files_to_add)

    # Add building data to the database
    sgc = DatabaseConstructor(dbc_obj=dbc_client)
    sgc.ogr_to_db(ogr_ls_dict)

    # Log the successfully added AGS to the log table in the database
    for a in ags_to_import:
        dbc_client.write_ags_log(int(a))

    gg.logger.info(f"Buildings for AGS {ags_to_import} have been successfully added to the database.")



def import_buildings_for_multiple_plz(df_plz_ags, dbc_client=None):
    """
    imports building data to db for multiple plz

    Args:
        df_plz_ags: DataFrame slice of municipal_register containing at least column 'ags'
        dbc_client: optional DatabaseClient to reuse an existing DB connection
    """
    created_client = dbc_client is None
    if created_client:
        # local import to avoid circular deps on module import
        import src.database.database_client as dbc

        dbc_client = dbc.DatabaseClient()

    # Define the path for building shapefiles
    data_path = os.path.abspath(os.path.join(PROJECT_ROOT, "raw_data", "buildings"))
    shapefiles_pattern = os.path.join(data_path, "*.shp")  # Pattern for shapefiles

    # retrieve all shape files
    files_list = glob.glob(shapefiles_pattern, recursive=True)

    # get all AGS that need to be imported for the classification
    ags_to_add = df_plz_ags['ags']
    ags_to_add = ags_to_add.tolist()
    ags_to_add = list(set(ags_to_add))  # dropping duplicates

    # check in ags_log if any ags are already on the database
    df_log = dbc_client.get_ags_log()
    log_ags_list = df_log['ags'].values.tolist()
    ags_to_add = list(set(ags_to_add).difference(log_ags_list))  # dropping already imported ags
    ags_to_add = list(map(str, ags_to_add))

    # creating a list that only contains the files to add
    files_to_add = []
    for file in files_list:
        for ags in ags_to_add:
            if ags in file:
                files_to_add.append(file)
    files_to_add = list(set(files_to_add))  # dropping duplicates

    if files_to_add:
        # define a list of required shapefiles to add to the database for the function scg.ogr_to_db()
        ogr_ls_dict = create_list_of_shp_files(files_to_add)

        # adding the buildings to the database
        sgc = DatabaseConstructor(dbc_obj=dbc_client)
        sgc.ogr_to_db(ogr_ls_dict)

        # adding the added ags to the log file
        for ags in ags_to_add:
            dbc_client.write_ags_log(int(ags))

    # If we created the client in this function, close it to avoid leaked connections
    if created_client:
        try:
            dbc_client.close()
        except Exception:
            pass

def create_list_of_shp_files(files_to_add):
    """
    Creates a list of dictionaries required for the scg.ogr_to_db() function.

    :param files_to_add: List of shapefile paths to add.
    :return: A list of dictionaries with keys "path" and "table_name".
    """
    ogr_ls_dict = []

    # Process each file path
    for file_path in files_to_add:
        # Determine table_name based on file naming convention
        if "Oth" in file_path:
            table_name = "oth"
        elif "Res" in file_path:
            table_name = "res"
        else:
            raise ValueError(f"Shapefile '{file_path}' cannot be assigned to 'res' or 'oth'.")

        ogr_ls_dict.append({"path": file_path, "table_name": table_name})

    # Ensure the list is not empty
    if ogr_ls_dict:
        return ogr_ls_dict
    else:
        raise Exception("No valid shapefiles found for the requested PLZ.")