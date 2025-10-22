#!/usr/bin/env python3
from pathlib import Path
import sys
import pandapower as pp
from src.analysis.topology_analysis import ParameterCalculator

# Allow running as a script from this directory
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from src.analysis.path_loader import load_config

def pp_get_json():
    data_dir, net_name, _projection = load_config()
    file_path = f"{data_dir}/{net_name}"
    json_path = f"{file_path}.json"
    net = pp.from_json(json_path)
    return net, file_path

def calc_grid_parameters_forchheim(self) -> None:
    """Calculate parameters for a single grid and save them."""
    net = pp_get_json()
    pc = ParameterCalculator()
    params = pc.compute_parameters(net)
    return params

if __name__ == "__main__":
    calc_grid_parameters_forchheim()