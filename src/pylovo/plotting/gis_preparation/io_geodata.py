"""
GIS gis_preparation functionality for grid data.

This module contains functions for exporting grid data to GIS-compatible formats
for visualization in QGIS and other geographic information systems.
"""

import json
from typing import Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from pylovo.grid_generator import GridGenerator


def get_bus_line_geo_for_network(
    pandapower_net,
    plz: int,
    net_index: int = 0
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Get bus and line geometric data for a single pandapower network.

    Exports lines (cables) and buses (trafo position, consumers, connections)
    as geometric elements suitable for GIS visualization.

    Parameters
    ----------
    pandapower_net : pandapowerNet
        The pandapower network to gis_preparation.
    plz : int
        Postal code.
    net_index : int, optional
        Network index for identification. Default: 0.

    Returns
    -------
    tuple of GeoDataFrame
        (line_geo, bus_geo) - GeoDataFrames containing line and bus geometries.
    """
    # Bus data - parse GeoJSON from geo column
    bus_geometries = []
    for idx, row in pandapower_net.bus.iterrows():
        if pd.notna(row.get("geo")):
            try:
                geo_dict = json.loads(row["geo"])
                coords = geo_dict["coordinates"]
                bus_geometries.append(Point(coords))
            except (json.JSONDecodeError, KeyError, TypeError):
                bus_geometries.append(None)
        else:
            bus_geometries.append(None)

    bus_geo = gpd.GeoDataFrame(pandapower_net.bus.copy(), geometry=bus_geometries)
    bus_geo['net'] = net_index
    bus_geo['consumer_bus'] = bus_geo['name'].str.contains("Consumer Nodebus")
    bus_geo['plz'] = plz

    bus_point_lookup = bus_geo.geometry.to_dict()

    # Line data - parse GeoJSON from geo column, or build a straight segment from bus points.
    line_geometries = []
    for _, row in pandapower_net.line.iterrows():
        geometry = None
        if pd.notna(row.get("geo")):
            try:
                geo_dict = json.loads(row["geo"])
                coords = geo_dict["coordinates"]
                geometry = LineString(coords)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                geometry = None

        line_geometries.append(geometry)

    line_geo = gpd.GeoDataFrame(pandapower_net.line.copy(), geometry=line_geometries)
    line_geo['net'] = net_index
    line_geo['plz'] = plz

    return line_geo, bus_geo


def get_bus_line_geo_for_plz(plz: int) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Get bus and line geometric data for all networks in a postal code.

    Parameters
    ----------
    plz : int
        Postal code.

    Returns
    -------
    tuple of GeoDataFrame
        (gdf_line, gdf_bus) - Combined GeoDataFrames for all networks in the PLZ.
    """
    # Connect to database
    gg = GridGenerator(plz=plz)
    dbc_client = gg.dbc

    # Find all networks
    cluster_list = dbc_client.get_list_from_plz(plz)

    # Initialize geo dataframes
    gdf_line = gpd.GeoDataFrame()
    gdf_bus = gpd.GeoDataFrame()

    # Index all networks
    net_index = 0

    # Loop over all networks and extract line and bus data
    for kcid, bcid in cluster_list:
        net = dbc_client.read_net_db(plz, kcid, bcid)
        line_geo, bus_geo = get_bus_line_geo_for_network(
            pandapower_net=net, net_index=net_index, plz=plz
        )

        gdf_line = pd.concat([gdf_line, line_geo])
        gdf_bus = pd.concat([gdf_bus, bus_geo])
        net_index += 1

    return gdf_line, gdf_bus


def save_geodata_as_csv(
    df_plz: pd.DataFrame,
    data_path_lines: str,
    data_path_bus: str
) -> None:
    """
    Save geodata to CSV files for multiple postal codes.

    Parameters
    ----------
    df_plz : pd.DataFrame
        DataFrame containing 'plz' column with postal codes to gis_preparation.
    data_path_lines : str
        Path to save the lines CSV file.
    data_path_bus : str
        Path to save the bus CSV file.
    """
    gdf_line = gpd.GeoDataFrame()
    gdf_bus = gpd.GeoDataFrame()

    for plz in df_plz['plz']:
        print(f"Saving geodata of plz: {plz} to csv.")
        gdf_line_tmp, gdf_bus_tmp = get_bus_line_geo_for_plz(plz)
        gdf_line = pd.concat([gdf_line, gdf_line_tmp])
        gdf_bus = pd.concat([gdf_bus, gdf_bus_tmp])

    gdf_line.to_csv(data_path_lines)
    gdf_bus.to_csv(data_path_bus)

