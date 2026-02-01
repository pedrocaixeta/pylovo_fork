import pandapower as pp
import json
import os

MASTER_PATH = "/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/SWF.json"
SUBNET_PATH = "/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/subnets/regular_nets/LV_028.json"

def inspect_relation():
    print("Loading Master...")
    net_master = pp.from_json(MASTER_PATH)
    print(f"Master Trafos: {len(net_master.trafo)}")
    print(net_master.trafo.head())
    
    print("\nLoading Subnet...")
    net_subnet = pp.from_json(SUBNET_PATH)
    print(f"Subnet Ext Grids: {len(net_subnet.ext_grid)}")
    print(net_subnet.ext_grid)
    
    # Check linkage
    ext_bus_id = net_subnet.ext_grid.bus.iloc[0]
    ext_bus_name = net_subnet.bus.at[ext_bus_id, 'name']
    print(f"\nSubnet Ext Grid Bus ID: {ext_bus_id}, Name: {ext_bus_name}")
    
    # Find this bus in master
    # Note: IDs might change, names usually persist
    master_bus = net_master.bus[net_master.bus['name'] == ext_bus_name]
    if not master_bus.empty:
        print(f"Found corresponding bus in Master: {master_bus.index.tolist()}")
        # Check if this bus is LV side of any trafo
        trafos = net_master.trafo[net_master.trafo.lv_bus.isin(master_bus.index)]
        if not trafos.empty:
            print("Connected Trafos in Master:")
            print(trafos)
        else:
            print("No direct trafo connection found in Master for this bus.")
    else:
        print("Bus name not found in Master.")

if __name__ == "__main__":
    inspect_relation()
