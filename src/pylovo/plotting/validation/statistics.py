"""
Spatial/geographic plotting functions.

This module contains functions for visualizing geographic data related to
postal codes (PLZ), including transformer distributions, cable types, and
grid statistics.
"""

from pathlib import Path
from typing import Tuple

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pandapower as pp
import plotly
import plotly.express as px
from pandapower.plotting.plotly import vlevel_plotly
from pandapower.plotting.plotly.mapbox_plot import set_mapbox_token

from pylovo.config_loader import RESULT_DIR, VERSION_ID
from pylovo.grid_generator import GridGenerator

# Try to import config, but don't fail if it doesn't exist
try:
    from pylovo.plotting import ACCESS_TOKEN_PLOTLY, PLOT_COLOR_DICT
    px.set_mapbox_access_token(ACCESS_TOKEN_PLOTLY)
except ImportError:
    ACCESS_TOKEN_PLOTLY = None
    PLOT_COLOR_DICT = {}


def plot_pie_of_trafo_cables(plz: int, figsize: Tuple[int, int] = (16, 4)) -> Figure:
    """
    Plot pie charts showing transformer size and cable type distributions for a postal code.

    Parameters
    ----------
    plz : int
        Postal code.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (16, 4).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the pie charts.
    """
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    data_list, data_labels, trafo_dict = dbc_client.read_per_trafo_dict(plz=plz)

    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=figsize)

    # Plot Transformer size distribution
    axs[0].pie(trafo_dict.values(), labels=trafo_dict.keys(), autopct='%1.1f%%',
               pctdistance=1.15, labeldistance=.6)
    axs[0].set_title('Transformer Size Distribution', fontsize=14)

    # Plot cable length distribution
    cable_dict = dbc_client.read_cable_dict(plz)
    axs[1].pie(cable_dict.values(), labels=cable_dict.keys(), autopct="%.1f%%")
    axs[1].set_title("Installed Cable Length", fontsize=14)
    plt.show()

    return fig


def plot_hist_trafos(plz: int, figsize: Tuple[int, int] = (10, 6)) -> Figure:
    """
    Plot histogram of transformer sizes in a postal code.

    Parameters
    ----------
    plz : int
        Postal code.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (10, 6).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the histogram.
    """
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    data_list, data_labels, trafo_dict = dbc_client.read_per_trafo_dict(plz=plz)

    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(trafo_dict.keys(), height=trafo_dict.values(), width=0.3)
    ax.set_title('Transformer Size Distribution', fontsize=14)
    ax.set_xlabel("Trafo size")
    ax.set_ylabel("Count")
    plt.show()

    return fig


def plot_boxplot_plz(plz: int, figsize: Tuple[int, int] = (16, 4)) -> Figure:
    """
    Create boxplots of grid parameters grouped by transformer size.

    Shows distribution of load numbers, bus numbers, simultaneous load peak,
    max/avg transformer distance for each transformer size category.

    Parameters
    ----------
    plz : int
        Postal code.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (16, 4).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the boxplots.
    """
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    data_list, data_labels, trafo_dict = dbc_client.read_per_trafo_dict(plz=plz)
    trafo_sizes = list(data_list[0].keys())
    values = [list(d.values()) for d in data_list]

    # Create the figure and axes objects
    fig, axs = plt.subplots(nrows=1, ncols=len(data_list), figsize=figsize, sharey=True)

    for i, data_label in enumerate(data_labels):
        axs[i].boxplot(values[i], labels=trafo_sizes, vert=False,
                       showfliers=False, patch_artist=True, notch=False)
        axs[i].set_title(data_label, fontsize=12)

    fig.supxlabel('Values', fontsize=12)
    fig.supylabel('Transformer Size (kVA)', fontsize=12)
    plt.tight_layout()
    plt.show()

    return fig


def plot_cable_length_of_types(plz: int, figsize: Tuple[int, int] = (10, 6)) -> Figure:
    """
    Plot distribution of cable length by cable type.

    Parameters
    ----------
    plz : int
        Postal code.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (10, 6).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the cable type distribution plot.
    """
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    cluster_list = dbc_client.get_list_from_plz(plz)
    cable_length_dict = {}

    for kcid, bcid in cluster_list:
        try:
            net = dbc_client.read_net_db(plz, kcid, bcid)
        except Exception as e:
            print(f"Local network {kcid},{bcid} is problematic")
            raise e
        else:
            cable_df = net.line[net.line["in_service"] == True]
            cable_types = pd.unique(cable_df["std_type"]).tolist()

            for cable_type in cable_types:
                cable_length = (
                    cable_df[cable_df["std_type"] == cable_type]["parallel"]
                    * cable_df[cable_df["std_type"] == cable_type]["length_km"]
                ).sum()

                if cable_type in cable_length_dict:
                    cable_length_dict[cable_type] += cable_length
                else:
                    cable_length_dict[cable_type] = cable_length

    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(cable_length_dict.keys(), height=cable_length_dict.values(), width=0.3)
    ax.set_title('Cable Type Distribution', fontsize=14)
    ax.set_xlabel("Cable type")
    ax.set_ylabel("Length in m")
    plt.show()

    return fig


def get_trafo_dicts(plz: int) -> Tuple[dict, dict, dict, dict]:
    """
    Retrieve load count, bus count, and cable length per transformer type for a postal code.

    Parameters
    ----------
    plz : int
        Postal code.

    Returns
    -------
    tuple of dict
        (load_count_dict, bus_count_dict, cable_length_dict, trafo_dict)
    """
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    cluster_list = dbc_client.get_list_from_plz(plz)

    load_count_dict = {}
    bus_count_dict = {}
    cable_length_dict = {}
    trafo_dict = {}

    print("Starting basic parameter counting")
    for kcid, bcid in cluster_list:
        load_count = 0
        bus_list = []
        net = dbc_client.read_net_db(plz, kcid, bcid)

        for row in net.load[["name", "bus"]].itertuples():
            load_count += 1
            bus_list.append(row.bus)

        bus_list = list(set(bus_list))
        bus_count = len(bus_list)
        cable_length = net.line['length_km'].sum()

        for row in net.trafo[["sn_mva", "lv_bus"]].itertuples():
            capacity = round(row.sn_mva * 1e3)

            if capacity in trafo_dict:
                trafo_dict[capacity] += 1
                load_count_dict[capacity].append(load_count)
                bus_count_dict[capacity].append(bus_count)
                cable_length_dict[capacity].append(cable_length)
            else:
                trafo_dict[capacity] = 1
                load_count_dict[capacity] = [load_count]
                bus_count_dict[capacity] = [bus_count]
                cable_length_dict[capacity] = [cable_length]

    return load_count_dict, bus_count_dict, cable_length_dict, trafo_dict


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
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc
    cluster_list = dbc_client.get_list_from_plz(plz)
    grid_index = 1

    # Set mapbox token for plotly maps
    set_mapbox_token("pk.eyJ1IjoiYmVuZWhhcm8iLCJhIjoiY205OGdwejJ1MDJsbzJsczl1ajdyYmlzaSJ9.HWA8ZLQm1Sp0Whs5PADxrw")

    for kcid, bcid in cluster_list:
        net = dbc_client.read_net_db(plz, kcid, bcid)
        for row in net.trafo[["sn_mva", "lv_bus"]].itertuples():
            trafo_size = round(row.sn_mva * 1e3)
            trafo_geom = np.array(net.bus_geodata.loc[row.lv_bus, ["x", "y"]])
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

