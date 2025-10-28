#!/usr/bin/env python3
"""
Plot All LV Subgrids on Single Interactive Map

This script creates a single interactive map showing all LV subgrids together.
Each transformer and its network are color-coded for easy identification.

Usage:
    python plot_all_on_map.py                      # Plot all 151 grids
    python plot_all_on_map.py --top 20            # Plot only top 20 largest
    python plot_all_on_map.py --filter-size Large  # Only large grids
    python plot_all_on_map.py --output map.html    # Custom output file
"""

import sys
from pathlib import Path
import argparse
import pandas as pd
import pandapower as pp
import plotly.graph_objects as go
import numpy as np

from src.analysis.utils import *

# Add project root to path
if '__file__' in globals():
    project_root = Path(__file__).parent.parent.parent.parent
else:
    project_root = Path.cwd()
sys.path.insert(0, str(project_root))

data_dir, net_name, _projection = load_validation_config()

# Paths
SUBGRIDS_DIR = project_root / data_dir
METRICS_CSV = SUBGRIDS_DIR.parent / "SWF_V7_metrics.csv"
OUTPUT_FILE = SUBGRIDS_DIR.parent


def get_color_palette(n):
    """Generate n distinct colors using HSV color space."""
    import colorsys
    colors = []
    for i in range(n):
        hue = i / n
        rgb = colorsys.hsv_to_rgb(hue, 0.8, 0.9)
        colors.append(f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})')
    return colors


def load_all_grids(grids_df):
    """Load all subgrids and extract geodata."""
    all_grids = []

    for idx, (_, row) in enumerate(grids_df.iterrows(), 1):
        grid_file = row['file']
        print(f"[{idx}/{len(grids_df)}] Loading {grid_file}...", end=" ")

        try:
            grid_path = SUBGRIDS_DIR / grid_file
            net = pp.from_json(str(grid_path))

            # Check if has geodata
            if len(net.bus_geodata) == 0:
                print("⚠ No geodata, skipping")
                continue

            # Get transformer info
            trafo_id = row['file'].split('trafo_')[1].split('.')[0]

            grid_data = {
                'file': grid_file,
                'trafo_id': trafo_id,
                'net': net,
                'branches': row['no_branches'],
                'buses': row['no_house_connections'],
                'loads': row['no_households']
            }

            all_grids.append(grid_data)
            print(f"✓ ({len(net.bus)} buses, {len(net.line)} lines)")

        except Exception as e:
            print(f"✗ Error: {e}")
            continue

    return all_grids


def create_combined_map(all_grids, output_file):
    """Create a single interactive map with all subgrids."""

    print(f"\n{'='*80}")
    print("CREATING COMBINED MAP")
    print(f"{'='*80}")

    fig = go.Figure()

    # Generate color palette
    colors = get_color_palette(len(all_grids))

    # Track overall bounds
    all_lats = []
    all_lons = []

    # Add each grid to the map
    for idx, grid_data in enumerate(all_grids):
        net = grid_data['net']
        color = colors[idx]
        grid_name = grid_data['file']

        print(f"[{idx+1}/{len(all_grids)}] Adding {grid_name} to map...")

        # Get transformer location
        if len(net.trafo) > 0:
            lv_bus = int(net.trafo['lv_bus'].iloc[0])
            if lv_bus in net.bus_geodata.index:
                trafo_lon = net.bus_geodata.loc[lv_bus, 'x']
                trafo_lat = net.bus_geodata.loc[lv_bus, 'y']

                # Add transformer marker
                fig.add_trace(go.Scattermapbox(
                    lon=[trafo_lon],
                    lat=[trafo_lat],
                    mode='markers',
                    marker=dict(
                        size=12,
                        color='red',
                        symbol='star'
                    ),
                    text=f"Transformer {grid_data['trafo_id']}<br>{grid_name}<br>"
                         f"Branches: {grid_data['branches']}<br>"
                         f"Buses: {grid_data['buses']}<br>"
                         f"Loads: {grid_data['loads']}",
                    hoverinfo='text',
                    name=f"Trafo {grid_data['trafo_id']}",
                    showlegend=False
                ))

                all_lats.append(trafo_lat)
                all_lons.append(trafo_lon)

        # Add lines
        if len(net.line) > 0 and len(net.line_geodata) > 0:
            line_lons = []
            line_lats = []

            for line_idx in net.line.index:
                if line_idx in net.line_geodata.index:
                    coords = net.line_geodata.loc[line_idx, 'coords']
                    if coords and len(coords) > 0:
                        for coord in coords:
                            line_lons.append(coord[0])
                            line_lats.append(coord[1])
                            all_lons.append(coord[0])
                            all_lats.append(coord[1])
                        # Add None to create line breaks between segments
                        line_lons.append(None)
                        line_lats.append(None)

            if line_lons:
                fig.add_trace(go.Scattermapbox(
                    lon=line_lons,
                    lat=line_lats,
                    mode='lines',
                    line=dict(width=1.5, color=color),
                    text=grid_name,
                    hoverinfo='text',
                    name=f"Grid {grid_data['trafo_id']}",
                    showlegend=True
                ))

        # Add buses
        if len(net.bus_geodata) > 0:
            bus_lons = []
            bus_lats = []
            bus_texts = []

            for bus_idx in net.bus.index:
                if bus_idx in net.bus_geodata.index:
                    bus_lons.append(net.bus_geodata.loc[bus_idx, 'x'])
                    bus_lats.append(net.bus_geodata.loc[bus_idx, 'y'])

                    # Check if bus has load
                    has_load = bus_idx in net.load['bus'].values if len(net.load) > 0 else False
                    bus_texts.append(f"Bus {bus_idx}<br>Grid: {grid_name}<br>Load: {'Yes' if has_load else 'No'}")

            if bus_lons:
                fig.add_trace(go.Scattermapbox(
                    lon=bus_lons,
                    lat=bus_lats,
                    mode='markers',
                    marker=dict(
                        size=4,
                        color=color,
                        opacity=0.6
                    ),
                    text=bus_texts,
                    hoverinfo='text',
                    name=f"Buses {grid_data['trafo_id']}",
                    showlegend=False
                ))

    # Calculate center and zoom
    if all_lats and all_lons:
        center_lat = np.mean(all_lats)
        center_lon = np.mean(all_lons)

        # Calculate zoom level based on bounds
        lat_range = max(all_lats) - min(all_lats)
        lon_range = max(all_lons) - min(all_lons)
        max_range = max(lat_range, lon_range)

        # Rough zoom calculation (adjust as needed)
        if max_range > 0.5:
            zoom = 10
        elif max_range > 0.1:
            zoom = 11
        elif max_range > 0.05:
            zoom = 12
        elif max_range > 0.01:
            zoom = 13
        else:
            zoom = 14
    else:
        center_lat, center_lon, zoom = 49.5, 11.0, 11  # Forchheim area default

    # Configure map layout
    fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom
        ),
        title=dict(
            text=f"All LV Subgrids - {len(all_grids)} Networks",
            font=dict(size=20),
            x=0.5,
            xanchor='center'
        ),
        height=900,
        hovermode='closest',
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.8)"
        )
    )

    # Save to HTML
    print(f"\nSaving map to {output_file}...")
    fig.write_html(str(output_file))

    print(f"\n{'='*80}")
    print("✓ MAP CREATED SUCCESSFULLY")
    print(f"{'='*80}")
    print(f"\nOutput file: {output_file}")
    print(f"File size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"\nOpen in browser: file://{output_file.absolute()}")
    print(f"\nMap contains:")
    print(f"  - {len(all_grids)} LV networks")
    print(f"  - {sum(len(g['net'].bus) for g in all_grids)} total buses")
    print(f"  - {sum(len(g['net'].line) for g in all_grids)} total lines")
    print(f"  - {sum(len(g['net'].trafo) for g in all_grids)} transformers")
    print(f"{'='*80}")

    return fig


def main():
    parser = argparse.ArgumentParser(
        description='Create a single interactive map showing all LV subgrids',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                # Plot all grids
  %(prog)s --top 20                      # Plot only top 20 largest grids
  %(prog)s --filter-size Large           # Only large grids
  %(prog)s --output my_map.html          # Custom output file
  %(prog)s --min-branches 10             # Only grids with ≥10 branches
        """
    )

    # Filtering
    parser.add_argument('--top', type=int, metavar='N',
                       help='Only plot top N largest grids')
    parser.add_argument('--filter-size', choices=['Tiny', 'Small', 'Medium', 'Large'],
                       help='Filter by size category')
    parser.add_argument('--min-branches', type=int, default=0,
                       help='Minimum number of branches (default: 0)')
    parser.add_argument('--max-branches', type=int,
                       help='Maximum number of branches')

    # Output
    parser.add_argument('--output', type=Path, default=OUTPUT_FILE,
                       help='Output HTML file (default: grid_data/subgrids/all_grids_map.html)')

    args = parser.parse_args()

    # Check paths
    if not SUBGRIDS_DIR.exists():
        print(f"❌ Subgrids directory not found: {SUBGRIDS_DIR}")
        return 1

    if not METRICS_CSV.exists():
        print(f"❌ Metrics CSV not found: {METRICS_CSV}")
        return 1

    # Load metrics and filter
    print("\n" + "="*80)
    print("LOADING METRICS")
    print("="*80)

    metrics_df = pd.read_csv(METRICS_CSV)

    # Add size category
    metrics_df['size_category'] = pd.cut(
        metrics_df['no_branches'],
        bins=[-float('inf'), 3, 10, 20, float('inf')],
        labels=['Tiny', 'Small', 'Medium', 'Large']
    )

    # Apply filters
    filtered = metrics_df[metrics_df['no_branches'] >= args.min_branches]

    if args.max_branches:
        filtered = filtered[filtered['no_branches'] <= args.max_branches]

    if args.filter_size:
        filtered = filtered[filtered['size_category'] == args.filter_size]

    if args.top:
        filtered = filtered.nlargest(args.top, 'no_branches')

    print(f"\nTotal subgrids available: {len(metrics_df)}")
    print(f"After filtering: {len(filtered)}")

    if args.filter_size:
        print(f"  Filter: {args.filter_size}")
    if args.min_branches > 0:
        print(f"  Min branches: {args.min_branches}")
    if args.max_branches:
        print(f"  Max branches: {args.max_branches}")
    if args.top:
        print(f"  Top: {args.top}")

    if len(filtered) == 0:
        print("\n❌ No grids match the criteria")
        return 1

    print(f"\nSize distribution:")
    for size, count in filtered['size_category'].value_counts().sort_index().items():
        print(f"  {size}: {count}")

    # Load all grids
    all_grids = load_all_grids(filtered)

    if len(all_grids) == 0:
        print("\n❌ No grids with geodata found")
        return 1

    # Create combined map
    create_combined_map(all_grids, args.output)

    return 0


if __name__ == '__main__':
    sys.exit(main())

