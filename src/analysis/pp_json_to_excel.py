#!/usr/bin/env python3
from pathlib import Path
import sys
import pandapower as pp

# Allow running as a script from this directory
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from src.analysis.path_loader import load_config

def pp_json_to_excel():
    net,file_path = pp_get_json()
    output_path = f"{file_path}.xlsx"
    pp.to_excel(net, output_path)
    print(f"Network data has been successfully exported to {output_path}")

def pp_get_json():
    data_dir, net_name, _projection = load_config()
    file_path = f"{data_dir}/{net_name}"
    json_path = f"{file_path}.json"
    net = pp.from_json(json_path)
    return net, file_path

if __name__ == "__main__":
    pp_json_to_excel()