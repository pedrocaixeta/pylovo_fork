"""
Geographic validation plotting functions.

This module contains functions for visualizing grid geometries and assets 
on geographic maps using Plotly and Mapbox.
"""

import json
from pathlib import Path
from typing import Optional, Tuple, Any

import numpy as np
import pandapower as pp
import plotly
import pandapower.plotting.plotly as pp_plotly 
from pandapower.plotting.plotly import vlevel_plotly
from pandapower.plotting.plotly.mapbox_plot import set_mapbox_token

from pylovo.config_loader import RESULT_DIR, VERSION_ID
from pylovo.plotting.utils import get_color_map

# Try to import config, but don't fail if it doesn't exist
try:
    from pylovo.plotting import ACCESS_TOKEN_PLOTLY, PLOT_COLOR_DICT
    # Default token if None
    set_mapbox_token(ACCESS_TOKEN_PLOTLY)
except ImportError:
    ACCESS_TOKEN_PLOTLY = None
    PLOT_COLOR_DICT = {}


def plot_trafo_on_map(plz: int, save_plots: bool = False) -> None:
    """
    Plot transformer types by their capacity on a plotly basemap.

    Parameters
    ----------
    plz : int
        Postal code.
    save_plots : bool, optional
        Whether to save the plots to file. Default: False.
    """
    net_plot = pp.create_empty_network()
    from pylovo.grid_generator import GridGenerator
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    cluster_list = dbc_client.get_list_from_plz(plz)
    grid_index = 1

    for kcid, bcid in cluster_list:
        try:
            net = dbc_client.read_net_db(plz, kcid, bcid)
        except Exception:
            continue

        for row in net.trafo[["sn_mva", "lv_bus"]].itertuples():
            trafo_size = round(row.sn_mva * 1e3)
            
            # Extract bus coordinates
            trafo_geom = None
            if "geo" in net.bus.columns and row.lv_bus in net.bus.index:
                geo_str = net.bus.at[row.lv_bus, "geo"]
                if geo_str and isinstance(geo_str, str):
                    try:
                        geo_data = json.loads(geo_str)
                        coords = geo_data.get("coordinates", [])
                        if len(coords) == 2:
                            trafo_geom = np.array([coords[0], coords[1]])
                    except (json.JSONDecodeError, ValueError):
                        pass
            elif hasattr(net, 'bus_geodata') and row.lv_bus in net.bus_geodata.index:
                 trafo_geom = np.array(net.bus_geodata.loc[row.lv_bus, ["x", "y"]])

            if trafo_geom is not None:
                pp.create_bus(
                    net_plot,
                    name=f"Distribution_grid_{grid_index}<br>transformer: {trafo_size}_kVA",
                    vn_kv=trafo_size,
                    geodata=tuple(trafo_geom),
                    type="b",
                )
            grid_index += 1

    figure = vlevel_plotly(
        net_plot, on_map=True, colors_dict=PLOT_COLOR_DICT, projection="epsg:4326"
    )

    if save_plots:
        savepath_folder = Path(RESULT_DIR, "figures", f"version_{VERSION_ID}", str(plz))
        savepath_folder.mkdir(parents=True, exist_ok=True)
        savepath_file = Path(savepath_folder, "trafo_on_map.html")
        plotly.offline.plot(figure, filename=str(savepath_file))
    
    return figure


def plot_grid_on_map_plotly(
    plz: int, 
    kcid: int, 
    bcid: int, 
    title: Optional[str] = None
) -> Any:
    """
    Visualize a single specific grid on a Mapbox map using pandapower.plotting.plotly.
    
    Parameters
    ----------
    plz : int
        Postal code
    kcid : int
        Grid cluster ID
    bcid : int
        Building cluster ID
    title : str, optional
        Title of the plot
        
    Returns
    -------
    plotly.graph_objects.Figure
    """
    from pylovo.grid_generator import GridGenerator
    gg = GridGenerator(plz=plz)
    try:
        net = gg.dbc.read_net_db(plz, kcid, bcid)
    except Exception as e:
        print(f"Could not load grid {kcid}-{bcid}: {e}")
        return None
        
    # Simplify plot using simple_plotly or vlevel depending on detail needed
    # on_map=True enables Mapbox background
    
    # Ensure geodata checks passed implicitly by pandapower plotting
    try:
        fig = pp_plotly.simple_plotly(net, on_map=True)
        if title:
            fig.update_layout(title_text=title)
        return fig

    except Exception as e:
        print(f"Plotting failed: {e}")
        return None

def plot_all_grids_detailed(plz: int, title: str = "Full Grid Comparison") -> Any:
    """
    Plot ALL grids (lines and transformers) in the PLZ.
    WARNING: This can be slow (~1-2 mins) and heavy to render.
    """
    from pylovo.grid_generator import GridGenerator
    from tqdm import tqdm
    
    gg = GridGenerator(plz=plz)
    cluster_list = gg.dbc.get_list_from_plz(plz)
    
    net_all = pp.create_empty_network()
    
    print(f"Loading and merging {len(cluster_list)} grids...")
    
    for kcid, bcid in tqdm(cluster_list, desc="Merging Grids"):
        try:
            net = gg.dbc.read_net_db(plz, kcid, bcid)
            
            # Bus mapping: old_id -> new_id
            bus_map = {}
            
            # Add Buses
            # Faster iteration
            for idx, row in net.bus.iterrows():
                # Extract Geo
                geo = None
                if "geo" in net.bus.columns:
                     geo_str = row.get("geo")
                     if geo_str and isinstance(geo_str, str):
                         try:
                             d = json.loads(geo_str)
                             geo = d.get("coordinates")
                         except: pass
                
                # If geo missing in column, check bus_geodata
                if not geo and hasattr(net, 'bus_geodata') and idx in net.bus_geodata.index:
                    geo = (net.bus_geodata.at[idx, 'x'], net.bus_geodata.at[idx, 'y'])
                
                if geo:
                    # Generic bus type
                    bid = pp.create_bus(net_all, vn_kv=0.4, geodata=geo)
                    bus_map[idx] = bid
            
            # Add Lines
            for idx, row in net.line.iterrows():
                if row.from_bus in bus_map and row.to_bus in bus_map:
                    # Handle line geodata if present
                    line_geo = None
                    # If geodata column exists and is valid
                    if 'geodata' in net.line.columns:
                         # Pandapower stores line geodata as list of tuples usually, or json
                         pass 
                         # For now let pandapower infer straight line if missing, 
                         # or copy if we can. 
                         # For speed, simple straight lines between buses is usually enough for "schematic"
                         # but for "Gis" we want the path.
                         # Copying geodata is complex if format varies.
                         # simple:
                    pp.create_line(net_all, bus_map[row.from_bus], bus_map[row.to_bus], 
                                   length_km=row.length_km, std_type=row.std_type)
                                   
        except Exception as e:
            continue

    print("Generating Map Plot...")
    fig = pp_plotly.simple_plotly(net_all, on_map=True)
    if title:
        fig.update_layout(title_text=title)
        
    return fig
