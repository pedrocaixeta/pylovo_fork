import logging
import os
from pathlib import Path
import pandas as pd
import geopandas as gpd
import pandapower as pp
from shapely import wkt
from shapely.geometry import Point

from pylovo.database.database_client import DatabaseClient
from pylovo.analysis.parameter_calculation import ParameterCalculator
from pylovo.utils import oneSimultaneousLoad, create_logger
from pylovo.config_loader import GRID_DATA_PATH, VERSION_ID

def process_synthetic_grids(dbc: DatabaseClient, plz: int):
    """
    Process all synthetic grids for a PLZ using ParameterCalculator.
    """
    print(f"Processing synthetic grids for PLZ {plz}...")
    calc = ParameterCalculator()
    calc.dbc = dbc # Reuse existing connection
    calc.calc_comparison_parameters_for_plz(plz)

def process_real_grids(dbc: DatabaseClient, data_path: str, plz: int):
    """
    Process real grids (SWF) with spatial matching using ParameterCalculator logic.
    """
    print(f"Processing real grids from {data_path}...")
    
    # 1. Fetch Buildings (Robust WKT)
    try:
        query = f"""
            SELECT br.osm_id, br.peak_load_in_kw, ST_AsText(br.geom) as wkt
            FROM buildings_result br
            JOIN grid_result gr ON br.grid_result_id = gr.grid_result_id
            WHERE gr.plz = {plz} AND br.version_id = '{VERSION_ID}'
        """
        buildings_df = pd.read_sql(query, dbc.sqla_engine)
        
        if not buildings_df.empty:
             buildings_df['geometry'] = buildings_df['wkt'].apply(wkt.loads)
             buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs="EPSG:3035")
        else:
             print("No buildings found for this PLZ.")
             return
    except Exception as e:
        print(f"Error fetching buildings: {e}")
        return

    path = Path(data_path)
    metrics_list = []
    calc = ParameterCalculator()
    
    for file_path in path.glob("*.json"):
        try:
            # Load Grid
            net = pp.from_json(str(file_path))
            
            # Spatial Match & Load Assignment
            # Check for bus coordinates
            if 'geo' in net.bus.columns and net.bus['geo'].notna().any():
                geoms = []
                indices = []
                for idx, row in net.bus.iterrows():
                    if isinstance(row['geo'], str):
                         try:
                             g = pd.io.json.loads(row['geo']) if hasattr(pd.io.json, 'loads') else pd.json_normalize(row['geo']) # json string
                             if isinstance(g, dict) and 'coordinates' in g:
                                geoms.append(Point(g['coordinates']))
                                indices.append(idx)
                             else:
                                # try standard json
                                import json
                                g = json.loads(row['geo'])
                                if 'coordinates' in g:
                                     geoms.append(Point(g['coordinates']))
                                     indices.append(idx)

                         except:
                             pass
                
                if geoms:
                    bus_gdf = gpd.GeoDataFrame({'bus_index': indices}, geometry=geoms, crs="EPSG:4326")
                    
                    if buildings_gdf.crs is None:
                        buildings_gdf.set_crs(epsg=3035, allow_override=True, inplace=True)
                    
                    if bus_gdf.crs.to_string() != buildings_gdf.crs.to_string():
                        bus_gdf = bus_gdf.to_crs(buildings_gdf.crs)
                        
                    # Join
                    joined = gpd.sjoin_nearest(buildings_gdf, bus_gdf, distance_col="dist")
                    print(f"DEBUG: Grid {file_path.stem}: Matched {len(joined)} buildings to buses.")
                    
                    # Group by bus
                    bus_counts = joined.groupby('bus_index')['osm_id'].count()
                    bus_loads = joined.groupby('bus_index')['peak_load_in_kw'].sum()
                    
                    # Update Net Loads
                    for bus_idx, total_load_kw in bus_loads.items():
                        count = bus_counts[bus_idx]
                        sim_factor = oneSimultaneousLoad(1.0, count, 0.07)
                        sim_load_mw = (total_load_kw / 1000.0) * sim_factor
                        
                        existing_loads = net.load[net.load.bus == bus_idx]
                        if not existing_loads.empty:
                            net.load.loc[existing_loads.index, 'p_mw'] = sim_load_mw
                        else:
                            pp.create_load(net, bus_idx, p_mw=sim_load_mw, name="Synthesized Load")

            # Calculate Metrics
            metrics = calc.calculate_comparison_metrics(net)
            metrics["grid_name"] = file_path.stem
            if metrics["max_voltage_drop"] == 0.0 or pd.isna(metrics["max_voltage_drop"]):
                 print(f"DEBUG: Grid {file_path.stem}: Max voltage drop is {metrics['max_voltage_drop']}. Total Load MW: {net.load.p_mw.sum()}")

            metrics_list.append(metrics)
            
        except Exception as e:
             print(f"Error processing real grid {file_path.name}: {e}")
             
    if metrics_list:
        df = pd.DataFrame(metrics_list)
        out_dir = Path("validation/metrics")
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "real_grid_metrics.csv"
        df.to_csv(csv_path, index=False)
        print(f"Saved real grid metrics to {csv_path}")

if __name__ == "__main__":
    plz = 91301
    print(f"Starting Grid Comparison Analysis for PLZ {plz}")
    
    with DatabaseClient() as dbc:
        # 1. Synthetic Grids (Updates DB + CSV)
        process_synthetic_grids(dbc, plz)
        
        # 2. Real Grids (Updates CSV)
        if GRID_DATA_PATH and os.path.exists(GRID_DATA_PATH):
             process_real_grids(dbc, GRID_DATA_PATH, plz)
        else:
             print(f"GRID_DATA_PATH not found or invalid: {GRID_DATA_PATH}")
