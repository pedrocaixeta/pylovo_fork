#!/usr/bin/env python3
"""
Benchmark analysis for external/DSO pandapower networks.

This module demonstrates how to analyze external networks (e.g., from DSO)
using the same topology analysis functions as synthetic grids, but without
requiring database access.

Handles both single-grid and multi-grid networks automatically.
"""
from pathlib import Path
import sys
import json
import pandas as pd

# Allow running as a script from this directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.utils import read_net_json, load_config
from src.analysis.data_adapter import adapt_dso_network
from src.analysis.standalone_calculator import StandaloneParameterCalculator
from src.analysis.multi_grid_splitter import split_multi_grid_network, analyze_multi_grid_network


def calc_grid_parameters_benchmark(
    adapt_network: bool = True,
    zone_mapping: dict = None,
    export_results: bool = True,
    max_grids: int = None
):
    """
    Calculate parameters for an external/DSO network.

    Parameters
    ----------
    adapt_network : bool
        Whether to adapt the network structure
    zone_mapping : dict, optional
        Mapping from DSO zone names to standard zones
    export_results : bool
        Whether to export results to JSON file
    max_grids : int, optional
        Maximum number of grids to analyze

    Returns
    -------
    dict or list of dict
        Dictionary of computed parameters (single grid) or list of dicts (multi-grid)
    """
    print("=" * 80)
    print("BENCHMARK ANALYSIS - External Network Parameter Calculation")
    print("=" * 80)

    # Load configuration and network
    print("\n1. Loading network...")
    data_dir, net_name, projection = load_config()
    print(f"   Data directory: {data_dir}")
    print(f"   Network name: {net_name}")
    print(f"   Projection: {projection}")

    net, file_path = read_net_json()
    print(f"   ✓ Network loaded successfully")
    print(f"   - Buses: {len(net.bus)}")
    print(f"   - Lines: {len(net.line)}")
    print(f"   - Loads: {len(net.load)}")
    print(f"   - Transformers: {len(net.trafo)}")

    # Detect if multi-grid network
    num_trafos = len(net.trafo)
    is_multi_grid = num_trafos > 1

    if is_multi_grid:
        print(f"\n   ⚠ Multi-grid network detected ({num_trafos} transformers)")
        print(f"   Will split into individual grids for analysis...")
        if max_grids:
            print(f"   Limiting to first {max_grids} grids")

        return analyze_multi_grid_benchmark(
            net, file_path, adapt_network, zone_mapping, export_results, max_grids
        )
    else:
        print(f"\n   ✓ Single-grid network detected")
        return analyze_single_grid_benchmark(
            net, file_path, adapt_network, zone_mapping, export_results
        )


def analyze_single_grid_benchmark(net, file_path, adapt_network, zone_mapping, export_results):
    """Analyze a single-grid network."""

    # Adapt network if requested
    if adapt_network:
        print("\n2. Adapting network structure...")
        print("   Normalizing bus names and zones for topology analysis...")

        # Default zone mapping for common DSO conventions
        default_zone_mapping = {
            'residential': 'Residential',
            'commercial': 'Commercial',
            'industrial': 'Commercial',
            'public': 'Public',
            'Wohngebäude': 'Residential',
            'Gewerbe': 'Commercial',
            'Industrie': 'Commercial',
        }

        if zone_mapping:
            default_zone_mapping.update(zone_mapping)

        net = adapt_dso_network(
            net,
            zone_mapping=default_zone_mapping,
            default_zone='Residential'
        )
        print("   ✓ Network adapted successfully")
    else:
        print("\n2. Skipping network adaptation (using original structure)")

    # Calculate parameters
    print("\n3. Computing topology parameters...")
    calculator = StandaloneParameterCalculator()
    params = calculator.compute_parameters_with_fallback(net, estimate_simultaneous_load=True)

    print("   ✓ Parameters computed successfully")

    # Display key results
    display_single_grid_results(params)

    # Export results
    if export_results:
        output_path = f"{file_path}_analysis_results.json"
        with open(output_path, 'w') as f:
            json.dump(params, f, indent=2)
        print(f"\n✓ Results exported to: {output_path}")

    print("\n" + "=" * 80)

    return params


def analyze_multi_grid_benchmark(net, file_path, adapt_network, zone_mapping, export_results, max_grids):
    """Analyze a multi-grid network."""

    print("\n2. Splitting into individual grids...")
    results = analyze_multi_grid_network(net, adapt_networks=adapt_network, max_grids=max_grids)

    print(f"\n   ✓ Successfully analyzed {len(results)} grids")

    # Display aggregate results
    display_multi_grid_results(results)

    # Export results
    if export_results:
        # Export detailed results as CSV
        csv_path = f"{file_path}_analysis_results.csv"
        df = pd.DataFrame(results)
        df.to_csv(csv_path, index=False)
        print(f"\n✓ Detailed results exported to: {csv_path}")

        # Export summary statistics as JSON
        summary_path = f"{file_path}_analysis_summary.json"
        summary = {
            'total_grids': len(results),
            'statistics': df.describe().to_dict()
        }
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"✓ Summary statistics exported to: {summary_path}")

    print("\n" + "=" * 80)

    return results


def display_single_grid_results(params):
    """Display results for a single grid."""
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"\nNetwork Topology:")
    print(f"  • Branches: {params['no_branches']}")
    print(f"  • House connections: {params['no_house_connections']}")
    print(f"  • Connection buses: {params['no_connection_buses']}")
    print(f"  • House connections per branch: {params['no_house_connections_per_branch']:.2f}")

    print(f"\nLoad Characteristics:")
    print(f"  • Number of households: {params['no_households']}")
    print(f"  • Household equivalents: {params['no_household_equ']:.2f}")
    print(f"  • Households per branch: {params['no_households_per_branch']:.2f}")
    print(f"  • Max households on a branch: {params['max_no_of_households_of_a_branch']:.2f}")
    print(f"  • Max power (MW): {params['max_power_mw']:.3f}")
    print(f"  • Simultaneous peak load (MW): {params['simultaneous_peak_load_mw']:.3f}")

    print(f"\nSpatial Metrics:")
    print(f"  • Average house distance (km): {params['house_distance_km']:.3f}")
    print(f"  • Average trafo distance (km): {params['avg_trafo_dis']:.3f}")
    print(f"  • Max trafo distance (km): {params['max_trafo_dis']:.3f}")
    print(f"  • Cable length (km): {params['cable_length_km']:.3f}")
    print(f"  • Cable length per house (km): {params['cable_len_per_house']:.3f}")

    print(f"\nTransformer:")
    print(f"  • Transformer rating (MVA): {params['transformer_mva']:.3f}")

    print(f"\nElectrical Characteristics:")
    print(f"  • Resistance (Ω·HE): {params['resistance']:.2f}")
    print(f"  • Reactance (Ω·HE): {params['reactance']:.2f}")
    print(f"  • R/X ratio: {params['ratio']:.2f}")
    print(f"  • VSW per branch: {params['vsw_per_branch']:.2f}")
    print(f"  • Max VSW of a branch: {params['max_vsw_of_a_branch']:.2f}")


def display_multi_grid_results(results):
    """Display aggregate results for multiple grids."""
    df = pd.DataFrame(results)

    print("\n" + "=" * 80)
    print("AGGREGATE RESULTS (All Grids)")
    print("=" * 80)

    print(f"\nNumber of grids analyzed: {len(results)}")

    print(f"\nTopology Statistics:")
    print(f"  • Branches per grid: {df['no_branches'].mean():.1f} ± {df['no_branches'].std():.1f}")
    print(f"  • House connections per grid: {df['no_house_connections'].mean():.1f} ± {df['no_house_connections'].std():.1f}")

    print(f"\nLoad Statistics:")
    print(f"  • Households per grid: {df['no_households'].mean():.1f} ± {df['no_households'].std():.1f}")
    print(f"  • Max power per grid (MW): {df['max_power_mw'].mean():.3f} ± {df['max_power_mw'].std():.3f}")

    print(f"\nSpatial Statistics:")
    print(f"  • Cable length per grid (km): {df['cable_length_km'].mean():.2f} ± {df['cable_length_km'].std():.2f}")
    print(f"  • Max trafo distance (km): {df['max_trafo_dis'].mean():.3f} ± {df['max_trafo_dis'].std():.3f}")

    print(f"\nTransformer Statistics:")
    print(f"  • Transformer rating (MVA): {df['transformer_mva'].mean():.3f} ± {df['transformer_mva'].std():.3f}")

    print(f"\nTotal across all grids:")
    print(f"  • Total households: {df['no_households'].sum()}")
    print(f"  • Total cable length (km): {df['cable_length_km'].sum():.2f}")
    print(f"  • Total max power (MW): {df['max_power_mw'].sum():.3f}")


if __name__ == "__main__":
    try:
        params = calc_grid_parameters_benchmark()
    except Exception as e:
        print(f"\n✗ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

