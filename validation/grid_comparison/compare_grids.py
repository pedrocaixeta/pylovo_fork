"""
Script to compare Real LV grids (from JSON files) vs Synthetic LV grids (from Database).
Refined to:
1. Use Real Transformers from Master Grid (SWF.json).
2. Filter Real Grids spatially (must be within PLZ 91301).
3. Use correct Load assumptions from Config.
4. Generate Boxplots and Histograms/KDEs.
"""
import sys
import os
import glob
import json
import pandas as pd
import pandapower as pp
import pandapower.topology as top
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from tqdm import tqdm
import geopandas as gpd
from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union
import traceback

from pylovo.analysis.parameter_calculation import ParameterCalculator
from pylovo.database.database_client import DatabaseClient
from pylovo.config_loader import PEAK_LOAD_HOUSEHOLD

# Configuration
REAL_DATA_PATH = r"/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/subnets/regular_nets"
MASTER_GRID_PATH = r"/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/SWF.json"
SYNTHETIC_PLZ = 91301
OUTPUT_DIR = Path(__file__).parent / "results"

def load_master_transformers():
    """Load master grid and return a lookup dict for transformers and std_types."""
    print("Loading Master Grid for Transformers...")
    try:
        net_master = pp.from_json(MASTER_GRID_PATH)
        # Create lookup: {lv_bus_name: trafo_row}
        lookup = {}
        for idx, row in net_master.trafo.iterrows():
            lv_bus_idx = row['lv_bus']
            lv_bus_name = net_master.bus.at[lv_bus_idx, 'name']
            lookup[lv_bus_name] = row
            
        std_types = net_master.std_types['trafo']
        print(f"Loaded {len(lookup)} transformers and {len(std_types)} std_types from Master.")
        return lookup, std_types
    except Exception as e:
        print(f"Failed to load Master Grid: {e}")
        return {}, None

def get_plz_polygon(plz):
    """Get the boundary polygon GDF for the PLZ."""
    print(f"Loading Polygon for PLZ {plz}...")
    dbc = DatabaseClient()
    query = "SELECT geom FROM postcode WHERE plz = %(p)s"
    try:
        # We return the GDF to preserve CRS info (usually 3035)
        gdf = gpd.read_postgis(query, dbc.conn, params={"p": str(plz)}, geom_col="geom")
        return gdf
    except Exception as e:
        print(f"Error fetching PLZ polygon: {e}")
    return None

def prepare_real_grid(net, trafo_lookup, master_std_types):
    """
    Preprocess Real Grid:
    1. Find Transformer in Lookup (via ext_grid bus name).
    2. Create Real Transformer in Subnet.
    3. Tag Buses.
    4. Set Load Defaults.
    """
    # 0. Inject Master Std Types (if available)
    if master_std_types is not None:
        if 'trafo' not in net.std_types:
             net.std_types['trafo'] = master_std_types
        else:
             # Merge/Update
             target = net.std_types['trafo']
             if isinstance(target, dict):
                 target = pd.DataFrame.from_dict(target)
             
             source = master_std_types
             if isinstance(source, dict):
                 source = pd.DataFrame.from_dict(source)
                 
             net.std_types['trafo'] = pd.concat([target, source])
             net.std_types['trafo'] = net.std_types['trafo'][~net.std_types['trafo'].index.duplicated(keep='last')]

    # 1. Handle Root / Trafo
    if net.trafo.empty and not net.ext_grid.empty:
        # Assuming single feed
        ext_id = net.ext_grid.bus.iloc[0]
        ext_name = net.bus.at[ext_id, 'name']
        
        # Tag root bus
        net.bus.at[ext_id, "name"] = str(ext_name) + " LVbus"
        
        # Look up in master
        trafo_data = trafo_lookup.get(ext_name)
        
        # Create MV Bus for connection
        mv_bus = pp.create_bus(net, vn_kv=20, name="MV_Source")
            
        if trafo_data is not None:
            # Use real parameters
            # std_type might be custom, so we set parameters manually if possible or try std_type
            try:
                pp.create_transformer(net, hv_bus=mv_bus, lv_bus=ext_id, 
                                      std_type=trafo_data['std_type'],
                                      sn_mva=trafo_data['sn_mva'],
                                      vn_hv_kv=trafo_data['vn_hv_kv'],
                                      vn_lv_kv=trafo_data['vn_lv_kv'],
                                      vk_percent=trafo_data['vk_percent'],
                                      vkr_percent=trafo_data['vkr_percent'],
                                      pfe_kw=trafo_data['pfe_kw'],
                                      i0_percent=trafo_data['i0_percent'],
                                      name=trafo_data['name'])
            except Exception as e:
                # print(f"Trafo creation failed for {ext_name} with type {trafo_data['std_type']}: {e}. Using fallback.")
                pp.create_transformer(net, hv_bus=mv_bus, lv_bus=ext_id, std_type="0.63 MVA 20/0.4 kV")
                if "sn_mva" not in net.trafo.columns or net.trafo["sn_mva"].isna().all():
                     net.trafo["sn_mva"] = 0.63
        else:
            # Fallback
            pp.create_transformer(net, hv_bus=mv_bus, lv_bus=ext_id, std_type="0.63 MVA 20/0.4 kV")
            if "sn_mva" not in net.trafo.columns or net.trafo["sn_mva"].isna().all():
                net.trafo["sn_mva"] = 0.63

    # 2. Handle Loads
    if "max_p_mw" not in net.load.columns:
        net.load["max_p_mw"] = PEAK_LOAD_HOUSEHOLD / 1000.0
    else:
        # Fill NaNs if any
        net.load["max_p_mw"] = net.load["max_p_mw"].fillna(PEAK_LOAD_HOUSEHOLD / 1000.0)

    # 3. Tag Consumer Buses
    load_buses = net.load.bus.unique()
    for b in load_buses:
        net.bus.at[b, "name"] = str(net.bus.at[b, "name"]) + " Consumer Nodebus"
        
    # 4. Tag Connection Buses (Approximate)
    mask = ~net.bus["name"].str.contains("LVbus|Consumer Nodebus", regex=True, na=False)
    net.bus.loc[mask, "name"] = net.bus.loc[mask, "name"].astype(str) + " Connection Nodebus"

    return net

def check_spatial_validity(net, polygon_gdf):
    """Check if the grid is roughly within the polygon (handling CRS)."""
    if polygon_gdf is None or polygon_gdf.empty or not hasattr(net, 'bus_geodata') or net.bus_geodata.empty:
        return True 
        
    # Create points from bus_geodata, Assume EPSG:32632 (UTM32N) for Real Grids in Germany
    points = [Point(x, y) for x, y in zip(net.bus_geodata.x, net.bus_geodata.y)]
    grid_gdf = gpd.GeoDataFrame(geometry=points, crs="EPSG:32632")
    grid_hull = grid_gdf.unary_union.convex_hull
    
    # Transform PLZ polygon to match Grid CRS
    # (Transforming one polygon is faster than transforming all grid points usually, 
    # but here we transformed points to create hull anyway)
    poly_transformed = polygon_gdf.to_crs(grid_gdf.crs).unary_union
    
    # Check intersection
    return poly_transformed.intersects(grid_hull)

def get_real_grids_metrics(data_path, limit=None):
    print(f"Loading Real Grids from {data_path}...")
    json_files = glob.glob(os.path.join(data_path, "*.json"))
    if limit:
        json_files = json_files[:limit]
    
    # Load requirements
    trafo_lookup, master_std_types = load_master_transformers()
    plz_polygon = get_plz_polygon(SYNTHETIC_PLZ)
    
    if plz_polygon is not None:
        print("Spatial filtering enabled.")
    else:
        print("Warning: Spatial filtering disabled (Polygon not found).")
        
    results = []
    pc = ParameterCalculator() 
    pc.plz = SYNTHETIC_PLZ
    
    skipped_spatial = 0
    
    for fpath in tqdm(json_files, desc="Real Grids"):
        try:
            net = pp.from_json(fpath)
            
            # Spatial Check
            if plz_polygon is not None:
                if not check_spatial_validity(net, plz_polygon):
                    skipped_spatial += 1
                    continue
            
            # Prepare
            net = prepare_real_grid(net, trafo_lookup, master_std_types)
            
            # Compute
            params = pc.compute_parameters(net)
            params['source'] = 'Real (SWF)'
            params['filename'] = os.path.basename(fpath)
            results.append(params)
            
        except Exception as e:
            print(f"Error processing {os.path.basename(fpath)}: {e}") 
            traceback.print_exc()
            continue
            
    if skipped_spatial > 0:
        print(f"Skipped {skipped_spatial} grids outside PLZ {SYNTHETIC_PLZ}.")
            
    return pd.DataFrame(results)

def get_synthetic_grids_metrics(plz, limit=None):
    print(f"Loading Synthetic Grids for PLZ {plz} from DB...")
    dbc = DatabaseClient()
    
    if not dbc.is_grid_generated(plz):
        print(f"Grid for PLZ {plz} is NOT generated in DB.")
        return pd.DataFrame()
        
    cluster_list = dbc.get_list_from_plz(plz)
    if limit:
        cluster_list = cluster_list[:limit]
        
    results = []
    pc = ParameterCalculator()
    pc.plz = plz
    
    for kcid, bcid in tqdm(cluster_list, desc="Synthetic Grids"):
        try:
            net = dbc.read_net_db(plz, kcid, bcid)
            params = pc.compute_parameters(net)
            params['source'] = f'Synthetic ({plz})'
            params['grid_id'] = f"{kcid}_{bcid}"
            results.append(params)
        except Exception as e:
            # print(f"Error processing {kcid}_{bcid}: {e}")
            continue
            
    return pd.DataFrame(results)

def plot_comparisons(df, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    metrics = [c for c in df.columns if c not in ['source', 'filename', 'grid_id']]
    
    # 1. Boxplots
    for metric in metrics:
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=df, x='source', y=metric)
        plt.title(f"Comparison: {metric}")
        plt.tight_layout()
        plt.savefig(output_dir / f"boxplot_{metric}.png")
        plt.close()
        
    # 2. Histograms / KDE
    # Limit to key metrics to avoid spamming 100 plots
    key_metrics = ['no_households', 'no_branches', 'cable_length_km', 'avg_trafo_dis', 'transformer_mva']
    for metric in metrics:
        if metric in key_metrics:
            plt.figure(figsize=(10, 6))
            sns.histplot(data=df, x=metric, hue='source', kde=True, element="step")
            plt.title(f"Distribution: {metric}")
            plt.tight_layout()
            plt.savefig(output_dir / f"hist_{metric}.png")
            plt.close()
        
    print(f"Plots saved to {output_dir}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit number of grids to process", default=None)
    parser.add_argument("--all", action="store_true", help="Process all grids (overrides limit)")
    args = parser.parse_args()
    
    limit = args.limit if not args.all else None
    
    # 1. Real Grids
    df_real = get_real_grids_metrics(REAL_DATA_PATH, limit=limit)
    
    # 2. Synthetic Grids
    df_synth = get_synthetic_grids_metrics(SYNTHETIC_PLZ, limit=limit)
    
    if df_real.empty:
        print("No real grid metrics calculated.")
    if df_synth.empty:
        print("No synthetic grid metrics calculated.")
        
    # 3. Merge & Save
    df_all = pd.concat([df_real, df_synth], ignore_index=True)
    
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    output_csv = OUTPUT_DIR / "comparison_metrics.csv"
    df_all.to_csv(output_csv, index=False)
    print(f"Metrics saved to {output_csv}")
    
    if not df_all.empty:
        plot_comparisons(df_all, OUTPUT_DIR)

if __name__ == "__main__":
    main()
