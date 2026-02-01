
import pandas as pd
import pandapower as pp
import glob
import os
from tqdm import tqdm
import re

# Config
REAL_DATA_PATH = r"/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/subnets/regular_nets"
MASTER_GRID_PATH = r"/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/SWF.json"

def analyze_details():
    # 1. Load Master for Trafo Lookup (to ensure we look at what was validated)
    print("Loading Master...")
    net_master = pp.from_json(MASTER_GRID_PATH)
    master_lookup = {}
    for idx, row in net_master.trafo.iterrows():
        lv_bus_idx = row['lv_bus']
        lv_bus_name = net_master.bus.at[lv_bus_idx, 'name']
        master_lookup[lv_bus_name] = row['sn_mva']

    # 2. Iterate Real Grids
    json_files = glob.glob(os.path.join(REAL_DATA_PATH, "*.json"))
    
    cable_stats = []
    trafo_stats = []
    kvs_stats = []
    
    print(f"Analyzing {len(json_files)} Real Grids...")
    for fpath in tqdm(json_files):
        try:
            net = pp.from_json(fpath)
            fname = os.path.basename(fpath)
            
            # --- Transformer MVA (via Master Lookup) ---
            # Find the root bus (ext_grid)
            if not net.ext_grid.empty:
                ext_id = net.ext_grid.bus.iloc[0]
                ext_name = net.bus.at[ext_id, 'name']
                
                real_mva = master_lookup.get(ext_name, None)
                if real_mva is not None:
                    trafo_stats.append(real_mva)
            
            # --- Cable Analysis ---
            # We look at lines. line.std_type might be None if custom
            # We care about type name and max_i_ka
            for idx, row in net.line.iterrows():
                std_type = row.get('std_type', 'custom')
                if pd.isna(std_type): std_type = 'custom'
                
                # Try to get max_i_ka from line directly or std_type
                max_i = row.get('max_i_ka')
                if pd.isna(max_i) and std_type != 'custom' and std_type in net.std_types['line']:
                    max_i = net.std_types['line'].at[std_type, 'max_i_ka']
                
                cable_stats.append({
                    'filename': fname,
                    'std_type': std_type,
                    'max_i_ka': max_i,
                    'length_km': row['length_km']
                })

            # --- KVS / Distribution Cabinet Analysis ---
            # User verified "NS_KVS" in 'name' column of bus
            kvs_buses = net.bus[net.bus['name'].astype(str).str.contains("NS_KVS", na=False)]
            if not kvs_buses.empty:
                kvs_stats.append({
                    'filename': fname,
                    'kvs_count': len(kvs_buses),
                    'kvs_names': kvs_buses['name'].tolist()
                })

        except Exception as e:
            print(f"Skipping {fname}: {e}")

    # --- AGGREGATE RESULTS ---
    
    # 1. Transformers
    print("\n" + "="*40)
    print("TRANSFORMER SIZES (Regular Nets)")
    print("="*40)
    msg_trafo = pd.Series(trafo_stats).value_counts().sort_index()
    print(msg_trafo)
    
    # 2. Cables
    print("\n" + "="*40)
    print("CABLE USAGE (Total Length km)")
    print("="*40)
    df_cable = pd.DataFrame(cable_stats)
    if not df_cable.empty:
        # Group by std_type and max_i_ka
        cable_summary = df_cable.groupby(['std_type', 'max_i_ka'])['length_km'].sum().sort_values(ascending=False)
        print(cable_summary)
        print("\nTop 10 Cables by Count:")
        print(df_cable['std_type'].value_counts().head(10))
    
    # 3. KVS
    print("\n" + "="*40)
    print("CABLE DISTRIBUTION CABINETS (NS_KVS)")
    print("="*40)
    print(f"Found KVS in {len(kvs_stats)} grids out of {len(json_files)}.")
    if kvs_stats:
        print(f"Average KVS per grid (where present): {pd.DataFrame(kvs_stats)['kvs_count'].mean():.2f}")
        print("Sample KVS names:")
        print(kvs_stats[0]['kvs_names'][:3])

if __name__ == "__main__":
    analyze_details()
