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
from pylovo.config_loader import ANALYZE_GRIDS, USE_INFDB


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
        try:
            # Import plotting functions only when needed
            from pylovo.plotting.validation import plot_boxplot_plz, plot_pie_of_trafo_cables

            # Plot data from the generated grids
            dbc_client = gg.dbc
            cluster_list = gg.dbc.get_list_from_plz(plz)
            print(f'The PLZ has {len(cluster_list)} grids.')
            plot_boxplot_plz(plz)
            plot_pie_of_trafo_cables(plz)
        except ImportError as e:
            print(f"Warning: Plotting packages not installed ({e})")
            print("Install with: uv sync --extra plots")
            print("Skipping plot generation.")


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
    """Main function to execute grid creation based on command-line arguments."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate synthetic LV distribution grids for specified regions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Generate for single postal code (PLZ)
  pylovo-generate --plz 80803

  # Generate for multiple postal codes
  pylovo-generate --plz 80803 80802 80801

  # Generate for single municipality (AGS)
  pylovo-generate --ags 09162000

  # Generate for multiple municipalities
  pylovo-generate --ags 09162000 09161000

  # Disable parallel processing (useful for debugging)
  pylovo-generate --plz 80803 --no-parallel

Regional Identifiers:
  PLZ: German postal codes (Postleitzahl) - 5-digit codes
  AGS: Municipality codes (Amtlicher Gemeindeschlüssel) - 8-digit codes
  
  You can find PLZ and AGS codes in your database after running pylovo-setup:
    SELECT plz, note FROM pylovo.postcode LIMIT 10;
    SELECT ags, gen FROM pylovo.municipal_register LIMIT 10;

For more information, see the README: https://github.com/tum-ens/pylovo
        '''
    )
    parser.add_argument('--plz', type=int, nargs='+',
                       help='Postal code(s) to generate grids for (e.g., 80803 or 80803 80802)')
    parser.add_argument('--ags', type=int, nargs='+',
                       help='Municipality code(s) (AGS) to generate grids for (e.g., 09162000)')
    parser.add_argument('--no-parallel', action='store_true',
                       help='Disable parallel processing for multiple regions')

    args = parser.parse_args()

    print("Pylovo Grid Creation Script")
    print("=" * 60)
    # Start timing the script
    start_time = time.time()

    try:
        # Determine what to do based on CLI arguments
        if args.plz:
            # Command-line PLZ argument(s) provided
            if len(args.plz) == 1:
                print(f"Creating grid for single PLZ: {args.plz[0]}")
                create_grid_single_plz(args.plz[0])
            else:
                print(f"Creating grids for multiple PLZ: {args.plz}")
                create_grid_multiple_plz(args.plz, parallel=not args.no_parallel)

        elif args.ags:
            # Command-line AGS argument(s) provided
            if len(args.ags) == 1:
                print(f"Creating grids for single AGS: {args.ags[0]}")
                create_grid_single_ags(args.ags[0])
            else:
                print(f"Creating grids for multiple AGS: {args.ags}")
                create_grid_multiple_ags(args.ags, parallel=not args.no_parallel)

        else:
            # No arguments provided - show helpful error
            print()
            print("❌ ERROR: No region specified")
            print("=" * 60)
            print("Please specify a region using --plz or --ags arguments:")
            print()
            print("  pylovo-generate --plz 80803         # Single postal code")
            print("  pylovo-generate --ags 09162000      # Single municipality")
            print()
            print("For more examples, run: pylovo-generate --help")
            print("=" * 60)
            sys.exit(1)

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

