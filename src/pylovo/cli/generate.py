"""
Unified Grid Creation Script for Pylovo

This script handles all grid creation scenarios based on configuration settings:

Regional Scale Options:
- postcode: Work at postcode level using PLZ codes
  - Single PLZ: Generate grid for one postal code (provide single integer)
  - Multiple PLZ: Generate grids for multiple postal codes (provide list of integers)
- municipality: Work at municipality level using AGS codes
  - Single AGS: Generate grids for all PLZ codes within one municipality (provide single AGS)
  - Multiple AGS: Generate grids for all PLZ codes within multiple municipalities (provide list of AGS)

The script automatically detects the execution mode based on the REGIONAL_SCALE and input type in config/config.yaml.
"""

import sys
import time
import pandas as pd
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.append(str(PROJECT_ROOT))

import pylovo.database.database_client as dbc
from pylovo.data_import.region_resolver import resolve_regions
from pylovo.data_import.import_buildings import import_buildings_for_single_plz, import_buildings_for_multiple_plz
from pylovo.grid_generator import GridGenerator
from pylovo.config_loader import ANALYZE_GRIDS, USE_INFDB, EXECUTION_MODE, PLZ, AGS
from pylovo.plotting.validation import plot_boxplot_plz, plot_pie_of_trafo_cables


def create_grid_single_plz(plz: int, plot_results: bool = False):
    """
    Create grid for a single PLZ.

    Args:
        plz: Postal code to generate grid for
        plot_results: Whether to generate plots after grid creation
    """
    print(f"Creating grid for single PLZ: {plz}")

    # Initialize GridGenerator with the provided postal code (PLZ)
    gg = GridGenerator(plz=plz)

    # Import building data to the database and get information about the plz
    if not USE_INFDB:
        import_buildings_for_single_plz(gg)

    # Generate a grid for the specified region
    gg.generate_grid_for_single_plz(plz=plz, analyze_grids=ANALYZE_GRIDS)

    if plot_results:
        # Plot data from the generated grids
        dbc_client = gg.dbc
        cluster_list = gg.dbc.get_list_from_plz(plz)
        print(f'The PLZ has {len(cluster_list)} grids.')
        plot_boxplot_plz(plz)
        plot_pie_of_trafo_cables(plz)


def create_grid_multiple_plz(plz_list: list, parallel: bool = True):
    """
    Create grids for multiple PLZ codes.

    Args:
        plz_list: List of postal codes to generate grids for
        parallel: Whether to use parallel processing
    """
    print(f"Creating grids for multiple PLZ: {plz_list}")

    if not USE_INFDB:
        with dbc.DatabaseClient() as dbc_client:
            _, df_plz_ags = resolve_regions(dbc_client, plz=[int(p) for p in plz_list])
            import_buildings_for_multiple_plz(df_plz_ags, dbc_client=dbc_client)

    # Initialize GridGenerator
    gg = GridGenerator()
    df_plz = pd.DataFrame({"plz": [int(p) for p in plz_list]})
    gg.generate_grid_for_multiple_plz(df_plz=df_plz, analyze_grids=ANALYZE_GRIDS, parallel=parallel)


def create_grid_single_ags(ags: int, parallel: bool = True):
    """
    Create grids for all PLZ codes within a single AGS.

    Args:
        ags: Amtlicher Gemeindeschlüssel (municipality code)
    """
    print(f"Creating grids for single AGS: {ags}")

    with dbc.DatabaseClient() as dbc_client:
        plz_list, df_plz_ags = resolve_regions(dbc_client, ags=int(ags))
        if not USE_INFDB:
            # Import buildings and generate grids
            import_buildings_for_multiple_plz(df_plz_ags, dbc_client=dbc_client)

    df_plz = pd.DataFrame({"plz": plz_list})

    # Initialize GridGenerator
    gg = GridGenerator()
    gg.generate_grid_for_multiple_plz(df_plz=df_plz, analyze_grids=ANALYZE_GRIDS, parallel=parallel)


def create_grid_multiple_ags(ags_list: list, parallel: bool = True):
    """
    Create grids for all PLZ codes within multiple AGS.

    Args:
        ags_list: List of Amtlicher Gemeindeschlüssel (municipality codes)
    """
    print(f"Creating grids for multiple AGS: {ags_list}")

    with dbc.DatabaseClient() as dbc_client:
        plz_list, df_plz_ags = resolve_regions(dbc_client, ags=[int(a) for a in ags_list])
        if not USE_INFDB:
            # Import buildings and generate grids
            import_buildings_for_multiple_plz(df_plz_ags, dbc_client=dbc_client)

    df_plz = pd.DataFrame({"plz": plz_list})

    # Initialize GridGenerator
    gg = GridGenerator()
    gg.generate_grid_for_multiple_plz(df_plz=df_plz, analyze_grids=ANALYZE_GRIDS, parallel=parallel)


def main():
    """Main function to execute grid creation based on configuration."""
    print("Pylovo Grid Creation Script")
    print("=" * 60)
    # Start timing the script
    start_time = time.time()

    try:
        if EXECUTION_MODE == "single_plz":
            create_grid_single_plz(PLZ)

        elif EXECUTION_MODE == "multiple_plz":
            create_grid_multiple_plz(PLZ)

        elif EXECUTION_MODE == "single_ags":
            create_grid_single_ags(AGS)

        elif EXECUTION_MODE == "multiple_ags":
            create_grid_multiple_ags(AGS)

        else:
            raise ValueError(f"Invalid execution mode: {EXECUTION_MODE}. "
                           f"Valid options are: single_plz, multiple_plz, single_ags, multiple_ags")

        # End timing and print results
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print(f"Elapsed Time: {int(minutes)} minutes and {seconds:.2f} seconds")

    except Exception as e:
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print("=" * 60)
        print(f"Error occurred during grid creation: {str(e)}")
        print(f"Elapsed Time: {int(minutes)} minutes and {seconds:.2f} seconds")
        print("=" * 60)
        raise


if __name__ == "__main__":
    main()

