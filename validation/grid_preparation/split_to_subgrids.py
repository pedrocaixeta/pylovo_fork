import pandapower as pp
import pandapower.plotting as pplot
import pandas as pd
from tqdm import tqdm
import os
import shutil

# CONFIGURATION
INPUT_FILE = "SWF_3.json"
OUTPUT_DIR = "subnets"
PLOT_PLOTS = False

def extract_mv_grid(net, output_dir):
    print("Extracting MV Grid...")
    mv_dir = os.path.join(output_dir, "regular") # MV counts as regular
    os.makedirs(mv_dir, exist_ok=True)
    
    mv_buses = net.bus[net.bus['chr_name'].str.startswith('5', na=False)].index.tolist()
    trafo_buses = list(net.trafo['hv_bus']) + list(net.trafo['lv_bus'])
    buses_to_keep = list(set(mv_buses + trafo_buses))
    
    try:
        mv_net = pp.select_subnet(net, buses=buses_to_keep, include_results=False)
        mv_net.name = "MV_5001"
        
        filename = f"{mv_dir}/MV_5001.json"
        pp.to_json(mv_net, filename)
        pp.to_excel(mv_net, f"{mv_dir}/MV_5001.xlsx")
        print(f"  Saved {filename} (Buses: {len(mv_net.bus)})")
    except Exception as e:
        print(f"  Failed to extract MV grid: {e}")

def extract_lv_grids(net, output_dir):
    print("Extracting LV Grids...")
    regular_dir = os.path.join(output_dir, "regular")
    mini_dir = os.path.join(output_dir, "mini_grids")
    os.makedirs(regular_dir, exist_ok=True)
    os.makedirs(mini_dir, exist_ok=True)
    
    # Pre-calculate IDs
    # 1. Bus IDs
    net.bus['sub_id'] = net.bus['chr_name'].apply(lambda x: x[1:4] if isinstance(x, str) and len(x)>4 and x.startswith('7') else None)
    
    # 2. Line IDs are NOT used to force inclusion. We use strict bus logic.
    # Lines connecting to neighbors are dropped, preserving radiality.
    
    unique_subnets = net.bus['sub_id'].dropna().unique()
    print(f"  Found {len(unique_subnets)} unique LV subnets.")
    
    for sub_id in tqdm(unique_subnets):
        try:
            # 1. Select buses strictly belonging to this subnet by name
            core_buses = net.bus[net.bus['sub_id'] == sub_id].index.tolist()
            
            # 2. Feeding Autos
            relevant_trafos = net.trafo[net.trafo['lv_bus'].isin(core_buses)]
            
            # 3. Create Subnet (Strict)
            lv_net = pp.select_subnet(net, buses=core_buses, include_results=False)
            lv_net.name = f"LV_{sub_id}"
            
            # 4. Ext Grid
            for _, trafo in relevant_trafos.iterrows():
                lv_bus = trafo['lv_bus']
                if lv_bus in lv_net.bus.index:
                    pp.create_ext_grid(lv_net, bus=lv_bus, name=f"Feed_from_{trafo['name']}")
                    
            # 5. Classify
            bus_count = len(lv_net.bus)
            target_folder = mini_dir if bus_count < 5 else regular_dir
            
            # Save
            filename = f"{target_folder}/LV_{sub_id}.json"
            pp.to_json(lv_net, filename)
            pp.to_excel(lv_net, filename.replace('.json', '.xlsx'))
            
        except Exception as e:
            print(f"    Error processing LV_{sub_id}: {e}")

def main():
    # Setup
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    
    print(f"Loading {INPUT_FILE}...")
    net = pp.from_json(INPUT_FILE)
    
    # MV Extraction
    extract_mv_grid(net, OUTPUT_DIR)
    
    # LV Extraction
    extract_lv_grids(net, OUTPUT_DIR)
    
    print("Done.")
