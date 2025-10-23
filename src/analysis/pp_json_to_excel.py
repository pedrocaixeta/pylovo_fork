#!/usr/bin/env python3
from pathlib import Path
import sys
import pandapower as pp
from utils import *

# Allow running as a script from this directory
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

def pp_json_to_excel():
    net,file_path = read_net_json()
    output_path = f"{file_path}.xlsx"
    pp.to_excel(net, output_path)
    print(f"Network data has been successfully exported to {output_path}")

if __name__ == "__main__":
    pp_json_to_excel()