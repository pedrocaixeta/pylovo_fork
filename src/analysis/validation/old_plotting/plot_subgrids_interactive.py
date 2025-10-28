#!/usr/bin/env python3
"""
Interactive Subgrid Visualization using Plotly.

This script uses the existing plotting functions from plotting/generation/networks.py
to create interactive map visualizations of LV subgrids.

Usage:
    python plot_subgrids_interactive.py                    # Show top grids
    python plot_subgrids_interactive.py <grid_filename>    # Plot specific grid
    python plot_subgrids_interactive.py --list             # List all grids
"""

import sys
from pathlib import Path
import argparse

# Add project root to path
if '__file__' in globals():
    project_root = Path(__file__).parent.parent.parent.parent
else:
    project_root = Path.cwd()
sys.path.insert(0, str(project_root))

import pandas as pd
import pandapower as pp
from pandapower.plotting.plotly import simple_plotly
from pandapower.topology import create_nxgraph

# Paths
SUBGRIDS_DIR = project_root / "grid_data" / "subgrids" / "SWF_V7"
METRICS_CSV = SUBGRIDS_DIR.parent / "SWF_V7_metrics.csv"


def list_grids(top_n=20):
    """List available grids with metrics."""
    metrics_df = pd.read_csv(METRICS_CSV)

    print("\n" + "="*80)
    print(f"TOP {top_n} LARGEST SUBGRIDS")
    print("="*80)

    top = metrics_df.nlargest(top_n, 'no_branches')

    print(f"\n{'File':<25} {'Branches':<10} {'Buses':<10} {'Loads':<10} {'Cable(km)':<12}")
    print("-"*80)

    for _, row in top.iterrows():
        print(f"{row['file']:<25} {row['no_branches']:<10.0f} "
              f"{row['no_house_connections']:<10.0f} "
              f"{row['no_households']:<10.0f} "
              f"{row['cable_length_km']:<12.2f}")

    print("\n" + "="*80)
    print(f"Total available: {len(metrics_df)} subgrids")
    print("="*80)

    return metrics_df


def plot_subgrid_interactive(grid_file, use_geodata=True, on_map=True):
    """
    Plot subgrid using interactive Plotly visualization.

    Parameters
    ----------
    grid_file : str
        Filename of the subgrid JSON
    use_geodata : bool
        Whether to use geographic coordinates (if available)
    on_map : bool
        Whether to plot on OpenStreetMap basemap
    """
    grid_path = SUBGRIDS_DIR / grid_file

    if not grid_path.exists():
        print(f"\n❌ Grid file not found: {grid_file}")
        print("\nAvailable grids (use --list to see all):")
        list_grids(top_n=10)
        return

    # Load grid
    print(f"\n{'='*80}")
    print(f"Loading: {grid_file}")
    print(f"{'='*80}")

    net = pp.from_json(str(grid_path))

    # Print info
    print(f"\nNetwork Info:")
    print(f"  Buses: {len(net.bus)}")
    print(f"  Lines: {len(net.line)}")
    print(f"  Transformers: {len(net.trafo)}")
    print(f"  Loads: {len(net.load)}")
    print(f"  Generators: {len(net.sgen)}")

    # Check if geodata exists
    has_geodata = len(net.bus_geodata) > 0 and len(net.line_geodata) > 0

    if has_geodata:
        print(f"\n✓ Geographic data available")
        print(f"  Bus geodata: {len(net.bus_geodata)} entries")
        print(f"  Line geodata: {len(net.line_geodata)} entries")
    else:
        print(f"\n⚠ No geographic data - will use generic layout")
        use_geodata = False
        on_map = False

    # Create interactive plot
    print(f"\n{'='*80}")
    print("Creating interactive plot...")
    print(f"  Geographic coordinates: {use_geodata}")
    print(f"  OpenStreetMap basemap: {on_map}")
    print(f"{'='*80}")

    try:
        if use_geodata and on_map:
            # Plot on map with geodata
            print("\n🗺️  Opening interactive map in browser...")
            fig = simple_plotly(net, on_map=True, map_style="open-street-map")
        elif use_geodata:
            # Plot with geodata but no basemap
            print("\n📍 Opening interactive plot with coordinates...")
            fig = simple_plotly(net, on_map=False)
        else:
            # Generic layout (no geodata)
            print("\n🔷 Opening interactive plot with generic layout...")
            from pandapower.plotting import create_generic_coordinates

            # Clear geodata to force generic layout
            net.bus_geodata.drop(net.bus_geodata.index, inplace=True)
            net.line_geodata.drop(net.line_geodata.index, inplace=True)

            # Create generic coordinates
            net = create_generic_coordinates(
                net,
                library='igraph',
                respect_switches=False,
                overwrite=True,
                geodata_table='bus_geodata'
            )

            fig = simple_plotly(net, aspectratio=(1, 1))

        print("\n✓ Plot opened in your default browser")
        print("  - Hover over elements for details")
        print("  - Click and drag to pan")
        print("  - Scroll to zoom")
        print("  - Use toolbar for more options")

    except Exception as e:
        print(f"\n❌ Error creating plot: {e}")
        print("\nTrying fallback generic layout...")

        try:
            from pandapower.plotting import create_generic_coordinates

            net.bus_geodata.drop(net.bus_geodata.index, inplace=True)
            net.line_geodata.drop(net.line_geodata.index, inplace=True)

            net = create_generic_coordinates(
                net,
                library='igraph',
                respect_switches=False,
                overwrite=True,
                geodata_table='bus_geodata'
            )

            fig = simple_plotly(net, aspectratio=(1, 1))
            print("\n✓ Fallback plot created successfully")

        except Exception as e2:
            print(f"\n❌ Fallback also failed: {e2}")
            return


def main():
    parser = argparse.ArgumentParser(
        description='Interactive visualization of LV subgrids using Plotly',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Show top 20 largest grids
  %(prog)s 041__trafo_105.json         # Plot specific grid on map
  %(prog)s --list                       # List all grids
  %(prog)s --top 50                     # Show top 50 grids
  %(prog)s 041__trafo_105.json --no-map  # Plot without basemap
        """
    )

    parser.add_argument('grid_file', nargs='?', help='Grid filename to visualize')
    parser.add_argument('--list', action='store_true', help='List all available grids')
    parser.add_argument('--top', type=int, default=20, help='Number of top grids to show (default: 20)')
    parser.add_argument('--no-map', action='store_true', help='Disable basemap (faster)')
    parser.add_argument('--generic', action='store_true', help='Force generic layout (ignore geodata)')

    args = parser.parse_args()

    # Check paths
    if not SUBGRIDS_DIR.exists():
        print(f"❌ Subgrids directory not found: {SUBGRIDS_DIR}")
        return 1

    if not METRICS_CSV.exists():
        print(f"❌ Metrics CSV not found: {METRICS_CSV}")
        return 1

    # Handle commands
    if args.list:
        list_grids(top_n=len(pd.read_csv(METRICS_CSV)))
        return 0

    if not args.grid_file:
        # Show top grids by default
        list_grids(top_n=args.top)
        print("\n💡 Tip: Run with a filename to visualize a specific grid")
        print(f"   Example: python {Path(__file__).name} 041__trafo_105.json")
        return 0

    # Plot the grid
    use_geodata = not args.generic
    on_map = use_geodata and not args.no_map

    plot_subgrid_interactive(args.grid_file, use_geodata=use_geodata, on_map=on_map)

    return 0


if __name__ == '__main__':
    sys.exit(main())

