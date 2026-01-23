"""
Import operations for pylovo data.
"""
import argparse
import sys
import time
import subprocess
from pathlib import Path

from pylovo.data_import.import_transformers import (
    get_trafos_processed_geojson_path,
    get_trafos_processed_3035_geojson_path,
    fetch_trafos,
    process_trafos,
    EPSG,
)
import pylovo.database.database_constructor


def import_transformers_osm(relation_id: int):
    """Fetch transformers from Overpass API and import to database."""
    start_time = time.time()

    print("Fetching transformers...")
    fetch_trafos(relation_id)

    print("Processing transformers...")
    process_trafos(relation_id)

    in_file = get_trafos_processed_geojson_path(relation_id)
    out_file = get_trafos_processed_3035_geojson_path(relation_id)

    # Convert the GeoJSON file to EPSG:3035
    subprocess.run(
        [
            "ogr2ogr",
            "-f", "GeoJSON",
            "-s_srs", f"EPSG:{EPSG}",
            "-t_srs", "EPSG:3035",
            out_file,
            in_file
        ],
        shell=False
    )

    # Load into database
    print("Loading transformers into database...")
    constructor = pylovo.database.database_constructor.DatabaseConstructor()
    constructor.transformers_to_db_from_geojson(out_file, clear_existing=False)

    elapsed = time.time() - start_time
    print(f"✓ Completed in {elapsed:.1f}s")


def import_transformers_ui():
    """Launch interactive UI for transformer management."""
    from pylovo.data_import.transformers_ui import main as ui_main
    ui_main()


def import_test_postcodes():
    """Import test postcode geometries for testing."""
    from pylovo.data_import.test_postcodes import main as test_main
    test_main()


def main():
    """Main entry point for import operations."""
    parser = argparse.ArgumentParser(
        prog="pylovo-import",
        description="Import various data into pylovo database",
        epilog="""
Examples:
  # Import transformers from OSM by relation ID
  pylovo-import transformers-osm --relation-id 62464
  
  # Launch interactive transformer UI
  pylovo-import transformers-ui
  
  # Import test postcode geometries
  pylovo-import test-postcodes
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Import operation to perform")

    # Subcommand: transformers-osm
    osm_parser = subparsers.add_parser(
        "transformers-osm",
        help="Fetch and import transformers from OpenStreetMap"
    )
    osm_parser.add_argument(
        "--relation-id",
        type=int,
        required=True,
        help="OSM relation ID of the area"
    )

    # Subcommand: transformers-ui
    subparsers.add_parser(
        "transformers-ui",
        help="Launch interactive UI for transformer management"
    )

    # Subcommand: test-postcodes
    subparsers.add_parser(
        "test-postcodes",
        help="Import test postcode geometries"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "transformers-osm":
            import_transformers_osm(args.relation_id)
        elif args.command == "transformers-ui":
            import_transformers_ui()
        elif args.command == "test-postcodes":
            import_test_postcodes()
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

