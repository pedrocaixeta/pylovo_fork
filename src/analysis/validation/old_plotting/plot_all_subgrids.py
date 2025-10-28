#!/usr/bin/env python3
"""
Plot All LV Subgrids - Batch Interactive Visualization

This script generates interactive Plotly visualizations for all LV subgrids.
You can choose to plot them one by one (with user confirmation) or save all to HTML files.

Usage:
    python plot_all_subgrids.py                    # Interactive mode - plot one by one
    python plot_all_subgrids.py --save-all         # Save all to HTML files
    python plot_all_subgrids.py --save-all --top 20  # Save only top 20 grids
    python plot_all_subgrids.py --filter-size Large  # Only large grids
"""

import sys
from pathlib import Path
import argparse
import time

# Add project root to path
if '__file__' in globals():
    project_root = Path(__file__).parent.parent.parent.parent
else:
    project_root = Path.cwd()
sys.path.insert(0, str(project_root))

import pandas as pd
import pandapower as pp
from pandapower.plotting.plotly import simple_plotly
from pandapower.plotting import create_generic_coordinates

# Paths
SUBGRIDS_DIR = project_root / "grid_data" / "subgrids" / "SWF_V7"
METRICS_CSV = SUBGRIDS_DIR.parent / "SWF_V7_metrics.csv"
OUTPUT_DIR = project_root / "grid_data" / "subgrids" / "visualizations"


def get_filtered_grids(size_filter=None, min_branches=0, max_branches=None, top_n=None):
    """Get filtered list of grids to plot."""
    metrics_df = pd.read_csv(METRICS_CSV)

    # Add size category
    metrics_df['size_category'] = pd.cut(
        metrics_df['no_branches'],
        bins=[-float('inf'), 3, 10, 20, float('inf')],
        labels=['Tiny', 'Small', 'Medium', 'Large']
    )

    # Apply filters
    filtered = metrics_df[metrics_df['no_branches'] >= min_branches]

    if max_branches:
        filtered = filtered[filtered['no_branches'] <= max_branches]

    if size_filter:
        filtered = filtered[filtered['size_category'] == size_filter]

    if top_n:
        filtered = filtered.nlargest(top_n, 'no_branches')

    return filtered


def plot_single_grid(grid_file, save_html=False, output_dir=None, on_map=True, verbose=True):
    """
    Plot a single grid interactively or save to HTML.

    Returns
    -------
    bool
        True if successful, False otherwise
    """
    grid_path = SUBGRIDS_DIR / grid_file

    if not grid_path.exists():
        if verbose:
            print(f"❌ Grid file not found: {grid_file}")
        return False

    try:
        # Load grid
        if verbose:
            print(f"Loading {grid_file}...")
        net = pp.from_json(str(grid_path))

        # Check if geodata exists
        has_geodata = len(net.bus_geodata) > 0 and len(net.line_geodata) > 0

        if not has_geodata:
            if verbose:
                print(f"  ⚠ No geodata - using generic layout")

            # Create generic coordinates
            net.bus_geodata.drop(net.bus_geodata.index, inplace=True)
            net.line_geodata.drop(net.line_geodata.index, inplace=True)

            net = create_generic_coordinates(
                net,
                library='igraph',
                respect_switches=False,
                overwrite=True,
                geodata_table='bus_geodata'
            )
            use_map = False
        else:
            use_map = on_map

        # Create plot
        if use_map:
            fig = simple_plotly(net, on_map=True, map_style="open-street-map")
        else:
            fig = simple_plotly(net, on_map=False)

        # Save or show
        if save_html:
            if output_dir is None:
                output_dir = OUTPUT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)

            html_file = output_dir / f"{grid_file.replace('.json', '.html')}"
            fig.write_html(str(html_file))

            if verbose:
                print(f"  ✓ Saved to {html_file.name}")
        else:
            if verbose:
                print(f"  ✓ Opening in browser...")
            fig.show()

        return True

    except Exception as e:
        if verbose:
            print(f"  ❌ Error: {e}")
        return False


def plot_all_interactive(grids_df, on_map=True):
    """Plot grids one by one with user confirmation."""
    total = len(grids_df)

    print("\n" + "="*80)
    print(f"INTERACTIVE MODE - {total} grids to plot")
    print("="*80)
    print("\nFor each grid:")
    print("  - Press ENTER to plot and continue")
    print("  - Type 's' to skip")
    print("  - Type 'q' to quit")
    print("="*80)

    plotted = 0
    skipped = 0

    for idx, (_, row) in enumerate(grids_df.iterrows(), 1):
        grid_file = row['file']

        print(f"\n[{idx}/{total}] {grid_file}")
        print(f"  Branches: {row['no_branches']:.0f}, "
              f"Buses: {row['no_house_connections']:.0f}, "
              f"Loads: {row['no_households']:.0f}")

        choice = input("  Action (ENTER/s/q): ").strip().lower()

        if choice == 'q':
            print("\n⏹ Quitting...")
            break
        elif choice == 's':
            print("  ⏭ Skipped")
            skipped += 1
            continue

        # Plot
        success = plot_single_grid(grid_file, save_html=False, on_map=on_map, verbose=True)
        if success:
            plotted += 1

        # Small delay to let browser catch up
        time.sleep(0.5)

    print("\n" + "="*80)
    print(f"SUMMARY: {plotted} plotted, {skipped} skipped, {total - plotted - skipped} failed")
    print("="*80)


def plot_all_save(grids_df, output_dir=None, on_map=True):
    """Save all grids to HTML files."""
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(grids_df)

    print("\n" + "="*80)
    print(f"BATCH SAVE MODE - {total} grids to save")
    print(f"Output: {output_dir}")
    print("="*80)

    successes = 0
    failures = 0

    for idx, (_, row) in enumerate(grids_df.iterrows(), 1):
        grid_file = row['file']
        print(f"[{idx}/{total}] {grid_file}...", end=" ")

        success = plot_single_grid(
            grid_file,
            save_html=True,
            output_dir=output_dir,
            on_map=on_map,
            verbose=False
        )

        if success:
            successes += 1
            print("✓")
        else:
            failures += 1
            print("✗")

    print("\n" + "="*80)
    print(f"SUMMARY: {successes} saved, {failures} failed")
    print(f"Output directory: {output_dir}")
    print("="*80)

    # Create index.html
    create_index_html(grids_df, output_dir)


def create_index_html(grids_df, output_dir):
    """Create an index.html file to browse all visualizations."""
    index_path = output_dir / "index.html"

    total_grids = len(grids_df)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>LV Subgrid Visualizations</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        a {{
            color: #4CAF50;
            text-decoration: none;
            font-weight: bold;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .stats {{
            margin: 20px 0;
            padding: 15px;
            background-color: white;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
    </style>
</head>
<body>
    <h1>🗺️ LV Subgrid Interactive Visualizations</h1>
    
    <div class="stats">
        <strong>Total Grids:</strong> {total_grids}<br>
        <strong>Generated:</strong> {timestamp}
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Grid</th>
                <th>Branches</th>
                <th>Consumer Buses</th>
                <th>Households</th>
                <th>Cable (km)</th>
                <th>Size</th>
            </tr>
        </thead>
        <tbody>
"""

    for _, row in grids_df.iterrows():
        html_file = row['file'].replace('.json', '.html')
        html_content += f"""
            <tr>
                <td><a href="{html_file}" target="_blank">{row['file']}</a></td>
                <td>{row['no_branches']:.0f}</td>
                <td>{row['no_house_connections']:.0f}</td>
                <td>{row['no_households']:.0f}</td>
                <td>{row['cable_length_km']:.2f}</td>
                <td>{row.get('size_category', 'N/A')}</td>
            </tr>
"""

    html_content += """
        </tbody>
    </table>
</body>
</html>
"""

    with open(index_path, 'w') as f:
        f.write(html_content)

    print(f"\n✓ Index created: {index_path}")
    print(f"  Open in browser: file://{index_path.absolute()}")


def main():
    parser = argparse.ArgumentParser(
        description='Plot all LV subgrids with interactive Plotly visualizations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                # Interactive mode - plot one by one
  %(prog)s --save-all                    # Save all to HTML files
  %(prog)s --save-all --top 20           # Save only top 20 largest grids
  %(prog)s --save-all --filter-size Large # Save only large grids
  %(prog)s --interactive --top 10        # Interactive mode with top 10
  %(prog)s --save-all --no-map          # Save without basemap (faster)
  %(prog)s --save-all --output ./my_viz  # Custom output directory
        """
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--save-all', action='store_true',
                           help='Save all grids to HTML files (batch mode)')
    mode_group.add_argument('--interactive', action='store_true',
                           help='Plot grids one by one with confirmation (default)')

    # Filtering
    parser.add_argument('--top', type=int, metavar='N',
                       help='Only process top N largest grids')
    parser.add_argument('--filter-size', choices=['Tiny', 'Small', 'Medium', 'Large'],
                       help='Filter by size category')
    parser.add_argument('--min-branches', type=int, default=0,
                       help='Minimum number of branches (default: 0)')
    parser.add_argument('--max-branches', type=int,
                       help='Maximum number of branches')

    # Options
    parser.add_argument('--no-map', action='store_true',
                       help='Disable basemap (faster rendering)')
    parser.add_argument('--output', type=Path,
                       help='Output directory for HTML files (default: grid_data/subgrids/visualizations)')

    args = parser.parse_args()

    # Check paths
    if not SUBGRIDS_DIR.exists():
        print(f"❌ Subgrids directory not found: {SUBGRIDS_DIR}")
        return 1

    if not METRICS_CSV.exists():
        print(f"❌ Metrics CSV not found: {METRICS_CSV}")
        return 1

    # Get filtered grids
    print("\n" + "="*80)
    print("LOADING GRIDS")
    print("="*80)

    grids_df = get_filtered_grids(
        size_filter=args.filter_size,
        min_branches=args.min_branches,
        max_branches=args.max_branches,
        top_n=args.top
    )

    print(f"\nFilters applied:")
    if args.top:
        print(f"  Top: {args.top}")
    if args.filter_size:
        print(f"  Size: {args.filter_size}")
    if args.min_branches > 0:
        print(f"  Min branches: {args.min_branches}")
    if args.max_branches:
        print(f"  Max branches: {args.max_branches}")

    print(f"\nGrids to process: {len(grids_df)}")

    if len(grids_df) == 0:
        print("\n❌ No grids match the criteria")
        return 1

    # Show summary
    print("\nSize distribution:")
    if 'size_category' in grids_df.columns:
        for size, count in grids_df['size_category'].value_counts().sort_index().items():
            print(f"  {size}: {count}")

    # Determine mode
    if args.save_all:
        # Batch save mode
        output_dir = args.output if args.output else OUTPUT_DIR
        plot_all_save(grids_df, output_dir=output_dir, on_map=not args.no_map)
    else:
        # Interactive mode (default)
        plot_all_interactive(grids_df, on_map=not args.no_map)

    return 0


if __name__ == '__main__':
    sys.exit(main())

