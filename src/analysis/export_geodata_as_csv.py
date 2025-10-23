#!/usr/bin/env python3
from pathlib import Path
import sys
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point
from tqdm import tqdm
import pandapower as pp

# Ensure we can import the local path_loader when run as a script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from utils import load_config

def export_geodata_as_csv():
    data_dir, json_filename, projection = load_config()
    data_dir, net_name, _projection = load_config()
    file_path = f"{data_dir}/{net_name}"

    out_lines = data_dir / "lines_multiple_grids.csv"
    out_buses = data_dir / "bus_multiple_grids.csv"

    # clear old results
    out_lines.unlink(missing_ok=True)
    out_buses.unlink(missing_ok=True)

    nets = list(_iter_nets_from_json(file_path))
    pbar = tqdm(total=len(nets), desc="Processing nets")

    all_lines, all_buses = [], []
    for idx, net in nets:
        line_gdf, bus_gdf = _get_bus_line_geo(net, idx, projection)
        all_lines.append(line_gdf)
        all_buses.append(bus_gdf)
        pbar.update(1)

    pbar.close()
    gdf_line = pd.concat(all_lines, ignore_index=True) if all_lines else gpd.GeoDataFrame()
    gdf_bus = pd.concat(all_buses, ignore_index=True) if all_buses else gpd.GeoDataFrame()

    # Ensure GeoDataFrame type after concat
    if not gdf_line.empty and "geometry" in gdf_line.columns and not isinstance(gdf_line, gpd.GeoDataFrame):
        gdf_line = gpd.GeoDataFrame(gdf_line, geometry="geometry", crs="EPSG:4326")
    if not gdf_bus.empty and "geometry" in gdf_bus.columns and not isinstance(gdf_bus, gpd.GeoDataFrame):
        gdf_bus = gpd.GeoDataFrame(gdf_bus, geometry="geometry", crs="EPSG:4326")

    # Convert geometry to WKT so QGIS can import
    if not gdf_line.empty and "geometry" in gdf_line.columns:
        gdf_line["geometry"] = gdf_line.geometry.to_wkt()
    if not gdf_bus.empty and "geometry" in gdf_bus.columns:
        gdf_bus["geometry"] = gdf_bus.geometry.to_wkt()

    # Write results next to the JSON
    if not gdf_line.empty:
        gdf_line.to_csv(out_lines, index=False)
    if not gdf_bus.empty:
        gdf_bus.to_csv(out_buses, index=False)

def _iter_nets_from_json(json_path: Path):
    """Load single or multiple pandapower nets from a JSON file."""
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


def _get_bus_line_geo(net, net_index: int, projection: str):
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



if __name__ == "__main__":
    export_geodata_as_csv()
