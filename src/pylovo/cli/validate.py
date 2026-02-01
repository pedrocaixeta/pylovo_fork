"""
Validation and metrics operations for pylovo grids.
"""
import argparse
import sys
import subprocess
from pathlib import Path


def run_comparison():
    """Run the grid comparison script."""
    # __file__ is src/pylovo/cli/validate.py
    # parents[0] = cli
    # parents[1] = pylovo
    # parents[2] = src
    # parents[3] = repo_root
    script_path = Path(__file__).parents[3] / "validation" / "grid_comparison" / "compare_grids.py"
    if not script_path.exists():
        print(f"Error: Comparison script not found at {script_path}")
        return
    
    print(f"Running comparison script: {script_path}")
    subprocess.run([sys.executable, str(script_path)])


def main():
    """Main entry point for validation operations."""
    parser = argparse.ArgumentParser(
        prog="pylovo-validate",
        description="Validation and metrics operations for pylovo grids"
    )

    subparsers = parser.add_subparsers(dest="command", help="Validation operation to perform")

    # Subcommand: compare-grids
    subparsers.add_parser(
        "compare-grids",
        help="Run comparison between Real and Synthetic grids"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "compare-grids":
            run_comparison()
        else:
             parser.print_help()
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

