"""
Helper functions for validation operations.

These functions support the validation CLI commands for processing
pandapower network JSON files and geodata export.
"""
import json
from pathlib import Path
import pandapower as pp
import geopandas as gpd
from shapely.geometry import LineString, Point


def iter_nets_from_json(json_path: Path):
    """
    Load single or multiple pandapower nets from a JSON file.

    Args:
        json_path: Path to JSON file containing network(s)

    Yields:
        Tuple of (index, pandapower_net)
    """
    try:
        net = pp.from_json(str(json_path))
        yield 0, net
        return
    except Exception:
        pass

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        for i, item in enumerate(data):
            tmp = json_path.parent / f"tmp_{i}.json"
            tmp.write_text(json.dumps(item), encoding="utf-8")
            yield i, pp.from_json(str(tmp))
            tmp.unlink(missing_ok=True)
    elif isinstance(data, dict):
        for i, item in enumerate(data.values()):
            tmp = json_path.parent / f"tmp_{i}.json"
            tmp.write_text(json.dumps(item), encoding="utf-8")
            yield i, pp.from_json(str(tmp))
            tmp.unlink(missing_ok=True)


def get_bus_line_geo(net, net_index: int, projection: str):
    """
    Extract bus and line geodata from a pandapower network.

    Args:
        net: Pandapower network
        net_index: Index identifier for the network
        projection: EPSG projection string (e.g., "epsg:3035")

    Returns:
        Tuple of (line_geodataframe, bus_geodataframe)
    """
    pp.plotting.plotly.geo_data_to_latlong(net, projection)

    # Lines
    line_geo_df = net.line_geodata.copy()
    if not line_geo_df.empty:
        lines = [LineString(c) if isinstance(c, (list, tuple)) and len(c) > 1 else None
                 for c in line_geo_df["coords"]]
        gdf_line = gpd.GeoDataFrame(line_geo_df, geometry=lines, crs="EPSG:4326")
        gdf_line["net"] = net_index
        gdf_line = gdf_line.merge(net.line, left_index=True, right_index=True, how="left")
        gdf_line = gdf_line[~gdf_line.geometry.isna()]
    else:
        gdf_line = gpd.GeoDataFrame(columns=["net", "geometry"], crs="EPSG:4326")

    # Buses
    bus_geo_df = net.bus_geodata.copy()
    if not bus_geo_df.empty:
        gdf_bus = gpd.GeoDataFrame(
            bus_geo_df,
            geometry=[Point(xy) for xy in zip(bus_geo_df["x"], bus_geo_df["y"])],
            crs="EPSG:4326"
        )
        gdf_bus["net"] = net_index
        gdf_bus = gdf_bus.merge(net.bus, left_index=True, right_index=True, how="left")
        gdf_bus["consumer_bus"] = gdf_bus.get("name", "").astype(str).str.contains("Consumer Nodebus", na=False)
    else:
        gdf_bus = gpd.GeoDataFrame(columns=["net", "consumer_bus", "geometry"], crs="EPSG:4326")

    return gdf_line, gdf_bus


__all__ = ["iter_nets_from_json", "get_bus_line_geo"]

