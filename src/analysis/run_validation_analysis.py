"""
Validation analysis script for external DSO networks.

This script:
1. Loads a multi-grid network from JSON (configured in config_validation.yaml)
2. Splits it into individual grids
3. Randomly selects 5 grids for analysis
4. Adapts each grid to match expected structure
5. Calculates topology metrics
6. Exports results to analysis directory
"""

import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
import pandapower as pp

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analysis.utils import (
    load_validation_config,
    read_net_json,
    create_logger,
    format_metrics_summary,
    format_multi_grid_summary
)
from src.analysis.tools.grid_splitter import split_multi_grid_network
from src.analysis.validation.network_adapter import NetworkAdapter
from src.analysis.validation.metrics_calculator import MetricsCalculator


def analyze_random_grids(
    net: pp.pandapowerNet,
    num_grids: int = 5,
    output_dir: Path = None,
    seed: int = 42
) -> List[Dict[str, Any]]:
    """
    Analyze random grids from a multi-grid network.

    Parameters
    ----------
    net : pp.pandapowerNet
        Multi-grid network to analyze
    num_grids : int
        Number of random grids to analyze (default: 5)
    output_dir : Path
        Directory to save results (default: src/analysis/net_results)
    seed : int
        Random seed for reproducibility (default: 42)

    Returns
    -------
    list[dict]
        List of metrics dictionaries for analyzed grids
    """
    logger = create_logger(
        "validation_analysis",
        str(Path(__file__).parent / "validation_analysis.log")
    )

    logger.info("=" * 80)
    logger.info("VALIDATION ANALYSIS - TESTING LATEST CHANGES")
    logger.info("=" * 80)

    # Set output directory
    if output_dir is None:
        output_dir = Path(__file__).parent / "net_results" / "validation_run"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Output directory: {output_dir}")

    # Step 1: Split multi-grid network
    logger.info("\nStep 1: Splitting multi-grid network...")
    logger.info(f"Network has {len(net.trafo)} transformers")

    grids = split_multi_grid_network(net, use_naming_convention=True)
    logger.info(f"Successfully split into {len(grids)} individual grids")

    # Step 2: Select random grids (prefer grids with loads and lines)
    random.seed(seed)

    # Filter grids to prefer those with actual content
    valid_grids = []
    for i, grid in enumerate(grids):
        if len(grid.load) > 0 and len(grid.line) > 0:
            valid_grids.append((i, grid, len(grid.load) + len(grid.line)))

    # If we have enough valid grids, select from them; otherwise use all grids
    if len(valid_grids) >= num_grids:
        logger.info(f"Found {len(valid_grids)} grids with loads and lines")
        # Sort by content (loads + lines) and pick diverse grids
        valid_grids.sort(key=lambda x: x[2], reverse=True)
        # Select a mix: some large, some medium, some small
        num_grids = min(num_grids, len(valid_grids))
        step = len(valid_grids) // num_grids
        selected_indices = [valid_grids[i * step][0] for i in range(num_grids)]
        selected_grids = [valid_grids[i * step][1] for i in range(num_grids)]
    else:
        logger.warning(f"Only {len(valid_grids)} grids have loads and lines, selecting from all grids")
        num_grids = min(num_grids, len(grids))
        selected_indices = sorted(random.sample(range(len(grids)), num_grids))
        selected_grids = [grids[i] for i in selected_indices]

    logger.info(f"\nStep 2: Selected {num_grids} grids for analysis")
    logger.info(f"Grid indices: {selected_indices}")

    # Step 3: Analyze each grid
    logger.info("\nStep 3: Analyzing selected grids...")

    results = []
    adapter = None  # Will be initialized for first grid
    calculator = MetricsCalculator()

    for idx, (grid_num, grid_net) in enumerate(zip(selected_indices, selected_grids), 1):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Analyzing Grid {idx}/{num_grids} (Grid #{grid_num})")
        logger.info(f"{'=' * 60}")
        logger.info(f"  Buses: {len(grid_net.bus)}, Lines: {len(grid_net.line)}, "
                   f"Loads: {len(grid_net.load)}, Trafos: {len(grid_net.trafo)}")

        try:
            # Adapt network structure
            logger.info("  → Adapting network structure...")
            adapter = NetworkAdapter(grid_net, naming_convention='auto')
            adapted_net = adapter.adapt()
            logger.info(f"  → Adaptation complete (convention: {adapter.naming_convention})")

            # Calculate metrics with simultaneous load estimation
            logger.info("  → Computing metrics...")
            metrics = calculator.compute_parameters_with_fallback(adapted_net, estimate_simultaneous_load=True)

            # Add grid identifier
            metrics['grid_index'] = grid_num
            metrics['grid_name'] = f"Grid_{grid_num}"

            # Log key metrics
            logger.info(f"  → Metrics computed successfully:")
            logger.info(f"     • Households: {metrics['no_households']}")
            logger.info(f"     • Branches: {metrics['no_branches']}")
            logger.info(f"     • Cable length: {metrics['cable_length_km']:.2f} km")
            logger.info(f"     • Max power: {metrics['max_power_mw']:.3f} MW")

            results.append(metrics)

            # Save individual grid results
            grid_output_dir = output_dir / f"grid_{grid_num}"
            grid_output_dir.mkdir(exist_ok=True)

            # Save metrics as JSON
            metrics_file = grid_output_dir / "metrics.json"
            with open(metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
            logger.info(f"  → Saved metrics to {metrics_file}")

            # Save formatted summary
            summary_file = grid_output_dir / "summary.txt"
            with open(summary_file, 'w') as f:
                f.write(format_metrics_summary(metrics))
            logger.info(f"  → Saved summary to {summary_file}")

            # Save network as JSON
            net_file = grid_output_dir / "network.json"
            pp.to_json(adapted_net, str(net_file))
            logger.info(f"  → Saved adapted network to {net_file}")

        except Exception as e:
            logger.error(f"  ✗ Error analyzing grid {grid_num}: {e}", exc_info=True)
            continue

    # Step 4: Export aggregate results
    logger.info(f"\n{'=' * 80}")
    logger.info("Step 4: Exporting aggregate results...")
    logger.info(f"{'=' * 80}")

    if results:
        # Save all metrics as CSV
        df_results = pd.DataFrame(results)
        csv_file = output_dir / "all_metrics.csv"
        df_results.to_csv(csv_file, index=False)
        logger.info(f"✓ Saved aggregate CSV to {csv_file}")

        # Save all metrics as JSON
        json_file = output_dir / "all_metrics.json"
        with open(json_file, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"✓ Saved aggregate JSON to {json_file}")

        # Save summary statistics
        summary_file = output_dir / "summary.txt"
        with open(summary_file, 'w') as f:
            f.write(format_multi_grid_summary(results))
        logger.info(f"✓ Saved summary statistics to {summary_file}")

        # Log summary to console
        logger.info("\n" + format_multi_grid_summary(results))

    else:
        logger.warning("No results to export!")

    logger.info(f"\n{'=' * 80}")
    logger.info(f"ANALYSIS COMPLETE - {len(results)}/{num_grids} grids analyzed successfully")
    logger.info(f"Results saved to: {output_dir}")
    logger.info(f"{'=' * 80}\n")

    return results


def main():
    """Main entry point for validation analysis."""
    # Load network from config
    print("Loading network from configuration...")
    net, file_path = read_net_json()
    print(f"Loaded network from: {file_path}.json")
    print(f"Network contains {len(net.trafo)} transformers, {len(net.bus)} buses, "
          f"{len(net.line)} lines, {len(net.load)} loads")

    # Analyze 5 random grids
    results = analyze_random_grids(net, num_grids=5, seed=42)

    if results:
        print(f"\n✓ Successfully analyzed {len(results)} grids")
        print(f"✓ Results saved to: src/analysis/net_results/validation_run/")
    else:
        print("\n✗ No grids were successfully analyzed")
        sys.exit(1)


if __name__ == "__main__":
    main()

