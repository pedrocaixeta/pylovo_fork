#!/usr/bin/env python3
"""
Convert pandapower JSON network to Excel format.

This tool reads a network from the configured JSON file and exports it to Excel.
"""
from pathlib import Path
import sys
import pandapower as pp

# Allow running as a script from this directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.utils import read_net_json


def convert_json_to_excel():
    """Convert configured JSON network to Excel format."""
    net, file_path = read_net_json()
    output_path = f"{file_path}.xlsx"
    pp.to_excel(net, output_path)
    print(f"✓ Network data has been successfully exported to {output_path}")
    print(f"  - Buses: {len(net.bus)}")
    print(f"  - Lines: {len(net.line)}")
    print(f"  - Loads: {len(net.load)}")
    print(f"  - Transformers: {len(net.trafo)}")


if __name__ == "__main__":
    convert_json_to_excel()
