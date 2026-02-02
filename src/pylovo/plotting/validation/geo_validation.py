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
    if ACCESS_TOKEN_PLOTLY is None:
        ACCESS_TOKEN_PLOTLY = "pk.eyJ1IjoiYmVuZWhhcm8iLCJhIjoiY205OGdwejJ1MDJsbzJsczl1ajdyYmlzaSJ9.HWA8ZLQm1Sp0Whs5PADxrw"
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
                    geodata=trafo_geom,
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
        fig = pp_plotly.simple_plotly(net, on_map=True, projection="epsg:4326")
        if title:
            fig.update_layout(title_text=title)
        return fig
    except Exception as e:
        print(f"Plotting failed: {e}")
        return None
