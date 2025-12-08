"""
Run metrics calculation for LV subgrid networks.

This script provides a command-line interface for computing metrics
on pandapower network JSON files and exporting the results to CSV.

Usage:
    python run_metrics.py <subgrids_dir> [--out OUTPUT_CSV] [--pattern PATTERN]

Examples:
    # Basic usage - analyze all JSON files in a directory
    python run_metrics.py /path/to/subgrids

    # Custom output file
    python run_metrics.py /path/to/subgrids --out my_metrics.csv

    # Custom file pattern
    python run_metrics.py /path/to/subgrids --pattern "grid_*.json"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add src to path if running from runme directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analysis.validation_swf.parameter_calculation_swf import ParameterCalculatorSWF


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the script."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def progress_callback(current: int, total: int, filename: str) -> None:
    """Print progress information."""
    percent = (current / total) * 100
    print(f"[{current}/{total}] ({percent:.1f}%) Processing: {filename}")


def main():
    """Main entry point for metrics calculation."""
    parser = argparse.ArgumentParser(
        description="Compute metrics for LV subgrid JSONs and export to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /data/subgrids
  %(prog)s /data/subgrids --out results.csv
  %(prog)s /data/subgrids --pattern "trafo_*.json" --verbose
        """
    )

    parser.add_argument(
        "subgrids_dir",
        help="Directory containing subgrid JSON files"
    )

    parser.add_argument(
        "--out",
        dest="output_csv",
        default="subgrids_metrics.csv",
        help="Output CSV path (default: subgrids_metrics.csv)"
    )

    parser.add_argument(
        "--pattern",
        default="*.json",
        help="Glob pattern for matching files (default: *.json)"
    )

    parser.add_argument(
        "--no-estimate-load",
        dest="estimate_load",
        action="store_false",
        help="Disable simultaneous load estimation"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Validate input directory
    subgrids_dir = Path(args.subgrids_dir)
    if not subgrids_dir.exists():
        logger.error(f"Directory not found: {subgrids_dir}")
        sys.exit(1)

    if not subgrids_dir.is_dir():
        logger.error(f"Not a directory: {subgrids_dir}")
        sys.exit(1)

    # Run analysis
    try:
        logger.info(f"Starting metrics calculation for: {subgrids_dir}")
        logger.info(f"Output file: {args.output_csv}")
        logger.info(f"File pattern: {args.pattern}")

        calculator = ParameterCalculatorSWF()
        df = calculator.analyze_batch(
            networks_dir=subgrids_dir,
            output_csv=args.output_csv,
            pattern=args.pattern,
            estimate_simultaneous_load=args.estimate_load,
            progress_callback=progress_callback if not args.verbose else None
        )

        # Print summary
        print("\n" + "="*70)
        print("METRICS CALCULATION COMPLETE")
        print("="*70)
        print(f"Total networks processed: {len(df)}")
        print(f"Output saved to: {args.output_csv}")

        if 'error' in df.columns:
            error_count = df['error'].notna().sum()
            if error_count > 0:
                print(f"\nWarning: {error_count} networks had errors")
                logger.warning(f"Failed networks: {df[df['error'].notna()]['file'].tolist()}")

        # Print basic statistics
        if len(df) > 0 and 'error' not in df.columns or df['error'].isna().all():
            print("\nKey Statistics:")
            print(f"  Average cable length: {df['cable_length_km'].mean():.2f} km")
            print(f"  Average transformer size: {df['transformer_mva'].mean():.3f} MVA")
            print(f"  Average house connections: {df['no_house_connections'].mean():.1f}")

        print("="*70)

    except Exception as e:
        logger.error(f"Failed to process networks: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

