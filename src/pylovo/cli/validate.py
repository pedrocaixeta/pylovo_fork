"""
Validation and metrics operations for pylovo grids.
"""
import argparse
import sys
from pathlib import Path


def convert_to_excel():
    """Convert configured JSON network to Excel format."""
    from pylovo.analysis.validation_swf.utils_swf import read_net_json
    import pandapower as pp

    net, file_path = read_net_json()
    output_path = f"{file_path}.xlsx"
    pp.to_excel(net, output_path)
    print(f"✓ Network exported to {output_path}")
    print(f"  - Buses: {len(net.bus)}")
    print(f"  - Lines: {len(net.line)}")
    print(f"  - Loads: {len(net.load)}")
    print(f"  - Transformers: {len(net.trafo)}")


def export_validation_geodata():
    """Export pandapower network geodata to CSV for QGIS."""
    from pylovo.analysis.validation_swf.utils_swf import load_validation_config
    import pandas as pd
    import geopandas as gpd
    from shapely.geometry import LineString, Point
    from tqdm import tqdm
    import pandapower as pp
    import json

    data_dir, net_name, projection = load_validation_config()
    file_path = data_dir / net_name

    out_lines = data_dir / "lines_multiple_grids.csv"
    out_buses = data_dir / "bus_multiple_grids.csv"

    # Clear old results
    out_lines.unlink(missing_ok=True)
    out_buses.unlink(missing_ok=True)

    # Import helper functions
    from pylovo.analysis.validation_helpers import iter_nets_from_json, get_bus_line_geo

    nets = list(iter_nets_from_json(file_path))
    pbar = tqdm(total=len(nets), desc="Processing nets")

    all_lines, all_buses = [], []
    for idx, net in nets:
        line_gdf, bus_gdf = get_bus_line_geo(net, idx, projection)
        all_lines.append(line_gdf)
        all_buses.append(bus_gdf)
        pbar.update(1)

    pbar.close()
    gdf_line = pd.concat(all_lines, ignore_index=True) if all_lines else gpd.GeoDataFrame()
    gdf_bus = pd.concat(all_buses, ignore_index=True) if all_buses else gpd.GeoDataFrame()

    # Save to CSV
    if not gdf_line.empty:
        gdf_line['geometry'] = gdf_line['geometry'].apply(lambda x: x.wkt)
        gdf_line.to_csv(out_lines, index=False)
        print(f"✓ Lines exported to {out_lines}")

    if not gdf_bus.empty:
        gdf_bus['geometry'] = gdf_bus['geometry'].apply(lambda x: x.wkt)
        gdf_bus.to_csv(out_buses, index=False)
        print(f"✓ Buses exported to {out_buses}")


def run_metrics(subgrids_dir, output_csv=None, pattern="*.json"):
    """Calculate metrics for LV subgrid networks."""
    from pylovo.analysis.validation_swf.parameter_calculation_swf import ParameterCalculatorSWF

    subgrids_path = Path(subgrids_dir)
    if not subgrids_path.exists():
        raise ValueError(f"Directory not found: {subgrids_dir}")

    if output_csv is None:
        output_csv = subgrids_path / "metrics.csv"

    print(f"Analyzing subgrids in: {subgrids_path}")
    print(f"Pattern: {pattern}")

    calc = ParameterCalculatorSWF()
    df = calc.calculate_metrics_from_directory(
        subgrids_path,
        pattern=pattern,
        progress_callback=lambda c, t, f: print(f"[{c}/{t}] {f}")
    )

    df.to_csv(output_csv, index=False)
    print(f"✓ Metrics saved to {output_csv}")
    print(f"  Processed {len(df)} networks")


def main():
    """Main entry point for validation operations."""
    parser = argparse.ArgumentParser(
        prog="pylovo-validate",
        description="Validation and metrics operations for pylovo grids",
        epilog="""
Examples:
  # Convert JSON network to Excel
  pylovo-validate convert-excel
  
  # Export validation geodata to CSV
  pylovo-validate export-geodata
  
  # Calculate metrics for subgrids
  pylovo-validate metrics /path/to/subgrids --out metrics.csv
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Validation operation to perform")

    # Subcommand: convert-excel
    subparsers.add_parser(
        "convert-excel",
        help="Convert pandapower JSON network to Excel"
    )

    # Subcommand: export-geodata
    subparsers.add_parser(
        "export-geodata",
        help="Export validation geodata to CSV for QGIS"
    )

    # Subcommand: metrics
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Calculate metrics for LV subgrids"
    )
    metrics_parser.add_argument(
        "subgrids_dir",
        help="Directory containing subgrid JSON files"
    )
    metrics_parser.add_argument(
        "--out",
        help="Output CSV file (default: <subgrids_dir>/metrics.csv)"
    )
    metrics_parser.add_argument(
        "--pattern",
        default="*.json",
        help="File pattern to match (default: *.json)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "convert-excel":
            convert_to_excel()
        elif args.command == "export-geodata":
            export_validation_geodata()
        elif args.command == "metrics":
            run_metrics(args.subgrids_dir, args.out, args.pattern)
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

