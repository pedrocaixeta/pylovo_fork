"""
Utility helpers for reading validation nets and exporting simple geodata views.
"""
import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandapower as pp
from tqdm import tqdm
from shapely.geometry import LineString, Point

# Subnets (real or synthetic) with fewer LV buses than this are classified as
# mini grids and excluded from the comparison dataset.
MINI_GRID_BUS_THRESHOLD = 5

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


def extract_mv_grid(net: pp.pandapowerNet, output_dir: Path | str) -> Path | None:
    """Extract and persist the MV part of a SWF validation net.

    The SWF source data encodes MV buses via `chr_name` prefixes. The extracted
    MV net keeps both MV buses and the transformer buses needed to preserve the
    interface to downstream LV grids.
    """
    output_dir = Path(output_dir)
    mv_dir = output_dir / "regular"
    mv_dir.mkdir(parents=True, exist_ok=True)

    if "chr_name" not in net.bus.columns:
        raise ValueError("Cannot extract the MV grid because the bus table has no 'chr_name' column.")

    mv_buses = net.bus[net.bus["chr_name"].fillna("").str.startswith("5", na=False)].index.tolist()
    trafo_buses = list(net.trafo["hv_bus"]) + list(net.trafo["lv_bus"])
    buses_to_keep = sorted(set(mv_buses + trafo_buses))
    if not buses_to_keep:
        return None

    mv_net = pp.select_subnet(net, buses=buses_to_keep, include_results=False)
    mv_net.name = "MV_5001"

    json_path = mv_dir / "MV_5001.json"
    pp.to_json(mv_net, str(json_path))
    pp.to_excel(mv_net, str(json_path.with_suffix(".xlsx")))
    return json_path


def extract_lv_grids(net: pp.pandapowerNet, output_dir: Path | str) -> list[Path]:
    """Extract and persist LV subnets from a SWF validation net.

    The extraction is intentionally strict: LV buses are grouped by their encoded
    subnet ID and neighboring buses are not force-included. This preserves the
    original radial subnet boundaries expected by the validation assets.
    """
    output_dir = Path(output_dir)
    regular_dir = output_dir / "regular"
    mini_dir = output_dir / "mini_grids"
    regular_dir.mkdir(parents=True, exist_ok=True)
    mini_dir.mkdir(parents=True, exist_ok=True)

    if "chr_name" not in net.bus.columns:
        raise ValueError("Cannot extract LV grids because the bus table has no 'chr_name' column.")

    bus_df = net.bus.copy()
    bus_df["sub_id"] = bus_df["chr_name"].apply(
        lambda value: value[1:4] if isinstance(value, str) and len(value) > 4 and value.startswith("7") else None
    )
    unique_subnets = bus_df["sub_id"].dropna().unique()

    saved_paths: list[Path] = []
    for sub_id in tqdm(unique_subnets):
        core_buses = bus_df[bus_df["sub_id"] == sub_id].index.tolist()
        if not core_buses:
            continue

        try:
            relevant_trafos = net.trafo[net.trafo["lv_bus"].isin(core_buses)]
            lv_net = pp.select_subnet(net, buses=core_buses, include_results=False)
            lv_net.name = f"LV_{sub_id}"

            for _, trafo_row in relevant_trafos.iterrows():
                lv_bus = trafo_row["lv_bus"]
                if lv_bus not in lv_net.bus.index:
                    continue

                # Feeder entry point: ext_grid at the LV bus keeps the subnet
                # solvable with the standard pandapower power-flow setup.
                pp.create_ext_grid(lv_net, bus=lv_bus, name=f"Feed_from_{trafo_row['name']}")

                # Carry over the full transformer element as an *out-of-service*
                # record so that net.trafo["sn_mva"] (and other electrical params
                # such as vk_percent, pfe_kw, tap settings, custom DSO columns) are
                # available without consulting the original full-model file again.
                # Marking it out-of-service prevents create_nxgraph from inserting
                # a topology edge, so feeder counting and distance metrics are
                # unaffected.
                hv_bus_orig = trafo_row["hv_bus"]
                vn_hv_kv = (
                    float(net.bus.at[hv_bus_orig, "vn_kv"])
                    if hv_bus_orig in net.bus.index
                    else float(trafo_row.get("vn_hv_kv", 20.0))
                )
                hv_dummy = pp.create_bus(
                    lv_net,
                    vn_kv=vn_hv_kv,
                    name=f"HV_{trafo_row['name']}",
                    type="b",
                    in_service=False,
                )
                new_trafo_idx = pp.create_transformer_from_parameters(
                    lv_net,
                    hv_bus=hv_dummy,
                    lv_bus=lv_bus,
                    sn_mva=float(trafo_row["sn_mva"]),
                    vn_hv_kv=vn_hv_kv,
                    vn_lv_kv=float(trafo_row.get("vn_lv_kv", 0.4)),
                    vk_percent=float(trafo_row.get("vk_percent", 4.0)),
                    vkr_percent=float(trafo_row.get("vkr_percent", 1.0)),
                    pfe_kw=float(trafo_row.get("pfe_kw", 0.0)),
                    i0_percent=float(trafo_row.get("i0_percent", 0.0)),
                    name=str(trafo_row.get("name", "")),
                    in_service=False,
                )
                # Copy all remaining columns (tap settings, zero-sequence params,
                # custom DSO fields like chr_name, Baujahr, std_type, …) from the
                # original trafo row.  hv_bus is intentionally skipped — it must
                # point to the dummy bus, not the original MV bus index.
                # in_service is skipped to preserve the False flag set above.
                _skip = {"hv_bus", "in_service"}
                for col, val in trafo_row.items():
                    if col in _skip or col.startswith("Unnamed"):
                        continue
                    if col not in lv_net.trafo.columns:
                        lv_net.trafo[col] = None
                    lv_net.trafo.at[new_trafo_idx, col] = val

            target_dir = mini_dir if len(core_buses) < MINI_GRID_BUS_THRESHOLD else regular_dir
            json_path = target_dir / f"LV_{sub_id}.json"
            pp.to_json(lv_net, str(json_path))
            pp.to_excel(lv_net, str(json_path.with_suffix(".xlsx")))
            saved_paths.append(json_path)
        except Exception:
            continue

    return saved_paths


def split_to_subgrids(
    input_file: Path | str,
    output_dir: Path | str,
    clear_output_dir: bool = True,
) -> dict[str, list[Path] | Path | None]:
    """Split a source validation net into one MV net and multiple LV subnets."""
    input_file = Path(input_file)
    output_dir = Path(output_dir)

    if clear_output_dir and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    net = pp.from_json(str(input_file))
    mv_path = extract_mv_grid(net, output_dir)
    lv_paths = extract_lv_grids(net, output_dir)
    return {"mv_grid": mv_path, "lv_grids": lv_paths}


def _resolve_convert_geodata_to_geojson():
    """Resolve the pandapower geojson conversion helper across version differences."""
    try:
        from pandapower.plotting.geo import convert_geodata_to_geojson
        return convert_geodata_to_geojson
    except ImportError:
        try:
            from pandapower.plotting import convert_geodata_to_geojson
            return convert_geodata_to_geojson
        except ImportError as exc:
            raise ImportError(
                "convert_geodata_to_geojson not found in pandapower.plotting or pandapower.plotting.geo"
            ) from exc


def fix_subnet_geos(base_dir: Path | str) -> tuple[int, int]:
    """Convert bus and line geodata of exported subnet JSON files into GeoJSON-ready form."""
    base_dir = Path(base_dir)
    convert_geodata_to_geojson = _resolve_convert_geodata_to_geojson()
    files = sorted(base_dir.glob("**/*.json"))

    success_count = 0
    fail_count = 0
    for file_path in tqdm(files):
        try:
            net = pp.from_json(str(file_path))
            convert_geodata_to_geojson(net, delete=False)
            pp.to_json(net, str(file_path))

            excel_path = file_path.with_suffix(".xlsx")
            if excel_path.exists():
                pp.to_excel(net, str(excel_path))

            success_count += 1
        except Exception:
            fail_count += 1

    return success_count, fail_count


__all__ = [
    "extract_lv_grids",
    "extract_mv_grid",
    "fix_subnet_geos",
    "get_bus_line_geo",
    "iter_nets_from_json",
    "MINI_GRID_BUS_THRESHOLD",
    "split_to_subgrids",
]

