"""
Consolidated export operations for pylovo.
"""
import os
import argparse
import pandas as pd

from pylovo.plotting.gis_preparation.io_geodata import save_geodata_as_csv, get_bus_line_geo_for_network
from pylovo.config_loader import PROJECT_ROOT
from pylovo.grid_generator import GridGenerator


def export_plz(plz_list, output_dir=None):
    """Export geodata for one or multiple PLZ."""
    if output_dir is None:
        output_dir = PROJECT_ROOT / "QGIS"

    os.makedirs(output_dir, exist_ok=True)

    df_plz = pd.DataFrame(plz_list, columns=['plz'])

    # Determine file names based on number of PLZ
    if len(plz_list) == 1:
        line_datapath = os.path.join(output_dir, "lines_single_grid.csv")
        bus_datapath = os.path.join(output_dir, "bus_single_grid.csv")
    else:
        line_datapath = os.path.join(output_dir, "lines_multiple_grids.csv")
        bus_datapath = os.path.join(output_dir, "bus_multiple_grids.csv")

    save_geodata_as_csv(df_plz=df_plz, data_path_lines=line_datapath, data_path_bus=bus_datapath)

    print(f"✓ Exported geodata for PLZ: {plz_list}")
    print(f"  Lines: {line_datapath}")
    print(f"  Buses: {bus_datapath}")


def export_grid(plz, kcid, bcid, output_dir=None):
    """Export geodata for a specific grid within a PLZ."""
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, 'QGIS')

    os.makedirs(output_dir, exist_ok=True)

    line_datapath = os.path.join(output_dir, 'lines_single_grid.csv')
    bus_datapath = os.path.join(output_dir, 'bus_single_grid.csv')

    # Read grid from DB
    gg = GridGenerator(plz)
    dbc_client = gg.dbc
    net = dbc_client.read_net_db(plz, kcid, bcid)

    # Get geodata
    line_geo, bus_geo = get_bus_line_geo_for_network(pandapower_net=net, plz=plz)

    # Save geodata to csv
    line_geo.to_csv(line_datapath)
    bus_geo.to_csv(bus_datapath)

    print(f"✓ Exported geodata for grid PLZ={plz}, kcid={kcid}, bcid={bcid}")
    print(f"  Lines: {line_datapath}")
    print(f"  Buses: {bus_datapath}")


def main():
    """Main entry point with different export modes."""
    parser = argparse.ArgumentParser(
        prog="pylovo-export",
        description="Export grid geodata to CSV for QGIS visualization",
        epilog="""
Examples:
  # Export single PLZ
  pylovo-export --plz 80803
  
  # Export multiple PLZ
  pylovo-export --plz 80803 80639 91720
  
  # Export specific grid within PLZ
  pylovo-export --grid --plz 91207 --kcid 4 --bcid 30
  
  # Custom output directory
  pylovo-export --plz 80803 --output /path/to/output
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--plz",
        nargs="+",
        required=True,
        help="Postal code(s) to export"
    )

    parser.add_argument(
        "--grid",
        action="store_true",
        help="Export specific grid (requires --kcid and --bcid)"
    )

    parser.add_argument(
        "--kcid",
        type=int,
        help="Cluster ID (for --grid mode)"
    )

    parser.add_argument(
        "--bcid",
        type=int,
        help="Branch/Bus cluster ID (for --grid mode)"
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output directory for CSV files (default: QGIS/)"
    )

    args = parser.parse_args()

    try:
        if args.grid:
            # Grid mode: export specific grid
            if not args.kcid or not args.bcid:
                parser.error("--grid mode requires --kcid and --bcid")
            if len(args.plz) != 1:
                parser.error("--grid mode requires exactly one PLZ")

            export_grid(args.plz[0], args.kcid, args.bcid, args.output)
        else:
            # PLZ mode: export one or more PLZ
            export_plz(args.plz, args.output)

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

