#!/usr/bin/env python3
"""
Validation suite for external/DSO networks.

This script provides a unified interface for all validation workflows:
  split       - Split multi-grid JSON into individual grids
  analyze     - Analyze single grid or multiple grids
  compare     - Compare DSO metrics with synthetic grid metrics
  export      - Export results to various formats

Usage:
  python run_validation.py split [--output-dir DIR]
  python run_validation.py analyze [--max-grids N] [--export]
  python run_validation.py export [--format json|csv|excel]
"""

import sys
import argparse
from pathlib import Path
import logging
import pandas as pd
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.validation import (
    NetworkAdapter,
    GridSplitter,
    MetricsCalculator,
    config as val_config
)
from src.analysis.utils import (
    format_metrics_summary,
    format_multi_grid_summary
)
import pandapower as pp


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cmd_split(args):
    """Split multi-grid network into individual grids."""
    logger.info("="*80)
    logger.info("SPLIT MULTI-GRID NETWORK")
    logger.info("="*80)

    # Load network
    logger.info("\n1. Loading network from config...")
    net, file_path = val_config.load_network_from_config()
    logger.info(f"   Network loaded: {len(net.bus)} buses, {len(net.trafo)} transformers")

    # Split
    logger.info("\n2. Splitting network...")
    splitter = GridSplitter(net, method='auto')
    grids = splitter.split()
    logger.info(f"   ✓ Split into {len(grids)} individual grids")

    # Save
    output_dir = args.output_dir or f"{file_path}_grids"
    logger.info(f"\n3. Saving grids to {output_dir}...")
    df_info = splitter.save_grids(
        grids,
        output_dir=output_dir,
        save_json=True,
        save_excel=False,
        save_info_csv=True
    )

    logger.info(f"\n✓ Successfully saved {len(df_info)} grids")
    logger.info(f"   Output directory: {output_dir}")
    logger.info("="*80)


def cmd_analyze(args):
    """Analyze network(s) and compute metrics."""
    logger.info("="*80)
    logger.info("ANALYZE NETWORK")
    logger.info("="*80)

    # Load network
    logger.info("\n1. Loading network...")
    net, file_path = val_config.load_network_from_config()
    logger.info(f"   Network: {len(net.bus)} buses, {len(net.trafo)} transformers")

    # Check if multi-grid
    is_multi_grid = len(net.trafo) > 1

    if is_multi_grid:
        logger.info(f"   ⚠ Multi-grid network detected ({len(net.trafo)} transformers)")
        logger.info("   Will analyze each grid separately...")

        # Split
        logger.info("\n2. Splitting into individual grids...")
        splitter = GridSplitter(net, method='auto')
        grids = splitter.split()

        if args.max_grids and args.max_grids < len(grids):
            grids = grids[:args.max_grids]
            logger.info(f"   Limiting to first {args.max_grids} grids")

        # Analyze each
        logger.info(f"\n3. Analyzing {len(grids)} grids...")
        results = []
        calculator = MetricsCalculator()

        for i, grid in enumerate(grids, 1):
            try:
                logger.info(f"   Analyzing grid {i}/{len(grids)}...")

                # Adapt
                adapter = NetworkAdapter(grid, naming_convention='auto')
                adapted = adapter.adapt()

                # Compute metrics
                metrics = calculator.compute_with_estimation(adapted)
                metrics['grid_id'] = i
                results.append(metrics)

            except Exception as e:
                logger.error(f"   Failed to analyze grid {i}: {e}")
                continue

        # Display results
        print("\n" + format_multi_grid_summary(results))

        # Export if requested
        if args.export:
            output_path = f"{file_path}_metrics.csv"
            df = pd.DataFrame(results)
            df.to_csv(output_path, index=False)
            logger.info(f"\n✓ Results exported to {output_path}")

    else:
        logger.info("   ✓ Single-grid network")

        # Adapt
        logger.info("\n2. Adapting network structure...")
        adapter = NetworkAdapter(net, naming_convention='auto')
        adapted = adapter.adapt()
        logger.info("   ✓ Network adapted")

        # Analyze
        logger.info("\n3. Computing metrics...")
        calculator = MetricsCalculator()
        metrics = calculator.compute_with_estimation(adapted)
        logger.info("   ✓ Metrics computed")

        # Display results
        print("\n" + format_metrics_summary(metrics))

        # Export if requested
        if args.export:
            output_path = f"{file_path}_metrics.json"
            with open(output_path, 'w') as f:
                json.dump(metrics, f, indent=2)
            logger.info(f"\n✓ Results exported to {output_path}")

    logger.info("\n" + "="*80)


def cmd_export(args):
    """Export network data in various formats."""
    logger.info("="*80)
    logger.info("EXPORT NETWORK DATA")
    logger.info("="*80)

    # Load network
    logger.info("\n1. Loading network...")
    net, file_path = val_config.load_network_from_config()
    logger.info(f"   Network loaded: {len(net.bus)} buses")

    # Export based on format
    logger.info(f"\n2. Exporting to {args.format}...")

    if args.format == 'excel':
        output_path = f"{file_path}.xlsx"
        pp.to_excel(net, output_path)
        logger.info(f"   ✓ Exported to {output_path}")

    elif args.format == 'json':
        output_path = f"{file_path}_copy.json"
        pp.to_json(net, output_path)
        logger.info(f"   ✓ Exported to {output_path}")

    elif args.format == 'csv':
        # Export main tables as CSV
        output_dir = f"{file_path}_csv"
        Path(output_dir).mkdir(exist_ok=True)

        net.bus.to_csv(f"{output_dir}/bus.csv")
        net.line.to_csv(f"{output_dir}/line.csv")
        net.load.to_csv(f"{output_dir}/load.csv")
        net.trafo.to_csv(f"{output_dir}/trafo.csv")

        logger.info(f"   ✓ Exported to {output_dir}/")

    logger.info("\n" + "="*80)


def cmd_compare(args):
    """Compare DSO metrics with synthetic grid metrics."""
    logger.info("="*80)
    logger.info("COMPARE METRICS")
    logger.info("="*80)
    logger.warning("This feature is not yet implemented.")
    logger.info("Future: Compare DSO grid metrics with synthetic grid database")
    logger.info("="*80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validation suite for external/DSO networks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Split command
    split_parser = subparsers.add_parser('split', help='Split multi-grid network')
    split_parser.add_argument('--output-dir', help='Output directory for split grids')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze network(s)')
    analyze_parser.add_argument('--max-grids', type=int, help='Max grids to analyze')
    analyze_parser.add_argument('--export', action='store_true', help='Export results')

    # Export command
    export_parser = subparsers.add_parser('export', help='Export network data')
    export_parser.add_argument('--format', choices=['json', 'csv', 'excel'],
                               default='excel', help='Export format')

    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare with synthetic grids')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == 'split':
            cmd_split(args)
        elif args.command == 'analyze':
            cmd_analyze(args)
        elif args.command == 'export':
            cmd_export(args)
        elif args.command == 'compare':
            cmd_compare(args)
        else:
            parser.print_help()
            return 1

        return 0

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

