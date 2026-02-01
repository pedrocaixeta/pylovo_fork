import sys
import os
import pandapower as pp
from pylovo.analysis.parameter_calculation import ParameterCalculator
from pylovo.database.database_client import DatabaseClient
from pylovo.config_loader import PEAK_LOAD_HOUSEHOLD
import traceback

# Copy of prepare logic
def prepare_real_grid(net):
    if net.trafo.empty and not net.ext_grid.empty:
        lv_bus = net.ext_grid.bus.iloc[0]
        net.bus.at[lv_bus, "name"] = str(net.bus.at[lv_bus, "name"]) + " LVbus"
        mv_bus = pp.create_bus(net, vn_kv=20, name="MV_Dummy")
        pp.create_transformer(net, hv_bus=mv_bus, lv_bus=lv_bus, std_type="0.63 MVA 20/0.4 kV")
        if "sn_mva" not in net.trafo.columns or net.trafo["sn_mva"].isna().all():
            net.trafo["sn_mva"] = 0.63
    if "max_p_mw" not in net.load.columns:
        net.load["max_p_mw"] = PEAK_LOAD_HOUSEHOLD / 1000.0
    load_buses = net.load.bus.unique()
    for b in load_buses:
        net.bus.at[b, "name"] = str(net.bus.at[b, "name"]) + " Consumer Nodebus"
    mask = ~net.bus["name"].str.contains("LVbus|Consumer Nodebus", regex=True, na=False)
    net.bus.loc[mask, "name"] = net.bus.loc[mask, "name"].astype(str) + " Connection Nodebus"
    return net

def test_real():
    print("\n--- Testing Single Real Grid ---")
    fpath = "/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/subnets/regular_nets/LV_028.json"
    try:
        net = pp.from_json(fpath)
        net = prepare_real_grid(net)
        pc = ParameterCalculator()
        params = pc.compute_parameters(net)
        print("Success!", params)
    except Exception:
        traceback.print_exc()

def test_synth():
    print("\n--- Testing Single Synthetic Grid (4_2) ---")
    dbc = DatabaseClient()
    try:
        # manual read for debug
        net = dbc.read_net_db(91301, 4, 2)
        pc = ParameterCalculator()
        params = pc.compute_parameters(net)
        print("Success!", params)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    test_real()
    test_synth()
