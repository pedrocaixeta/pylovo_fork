"""Helpers for comparing synthetic PyLoVo grids with real DSO grids."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd
import pandapower as pp
from shapely import wkt
from shapely.geometry import Point

from pylovo.analysis.grid_analysis import compute_comparison_parameters
from pylovo.config_loader import GRID_DATA_PATH, VERSION_ID
from pylovo.database.config_table_structure import CREATE_QUERIES
from pylovo.database.database_client import DatabaseClient

if TYPE_CHECKING:
    from pylovo.analysis.parameter_calculation import ParameterCalculator


def export_synthetic_comparison_parameters_for_plz(
    calculator: "ParameterCalculator",
    plz: int,
    limit: int = None,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Compute, persist, and export the active comparison parameter set for synthetic grids."""
    calculator.plz = plz

    calculator.dbc.cur.execute(CREATE_QUERIES["grid_parameters"])
    calculator.dbc.conn.commit()

    grids = calculator.dbc.get_list_from_plz(plz)
    if limit is not None:
        grids = grids[:limit]
    print(f"Calculating comparison parameters for {len(grids)} grids in PLZ {plz}...")

    metrics_list = []

    for kcid, bcid in grids:
        try:
            net = calculator.dbc.read_net_db(plz, kcid, bcid)
            calculator.dbc.cur.execute(
                "SELECT grid_result_id FROM grid_result WHERE plz=%s AND kcid=%s AND bcid=%s AND version_id=%s",
                (plz, kcid, bcid, calculator.version_id),
            )
            grid_result_id = calculator.dbc.cur.fetchone()[0]

            params = compute_comparison_parameters(calculator, net)
            params["grid_result_id"] = grid_result_id
            params["kcid"] = kcid
            params["bcid"] = bcid
            metrics_list.append(params)

            _upsert_comparison_parameters(calculator, grid_result_id, params)
        except Exception as exc:
            calculator.dbc.logger.error(f"Error processing grid {kcid}_{bcid}: {exc}")
            calculator.dbc.conn.rollback()

        calculator.dbc.conn.commit()

    calculator.dbc.conn.commit()

    if not metrics_list:
        return pd.DataFrame()

    df = pd.DataFrame(metrics_list)
    out_dir = Path(output_dir) if output_dir is not None else Path("validation/metrics")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "synthetic_grid_metrics.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved synthetic grid metrics to {csv_path}")
    return df


def iter_real_grid_files(data_path: str) -> list[Path]:
    """Return only LV JSON subnet files from the configured real-grid directory."""
    path = Path(data_path)
    return [file_path for file_path in sorted(path.glob("*.json")) if file_path.stem.startswith("LV_")]


def extract_bus_geometries(net: pp.pandapowerNet) -> gpd.GeoDataFrame:
    """Extract bus point geometries from pandapower bus.geo JSON strings."""
    geoms = []
    indices = []

    if "geo" not in net.bus.columns:
        return gpd.GeoDataFrame(columns=["bus_index", "geometry"], geometry="geometry", crs="EPSG:4326")

    for idx, row in net.bus.iterrows():
        geo_value = row.get("geo")
        if not isinstance(geo_value, str):
            continue
        try:
            geo_dict = json.loads(geo_value)
        except json.JSONDecodeError:
            continue

        coordinates = geo_dict.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            continue

        geoms.append(Point(coordinates[0], coordinates[1]))
        indices.append(idx)

    if not geoms:
        return gpd.GeoDataFrame(columns=["bus_index", "geometry"], geometry="geometry", crs="EPSG:4326")

    xs = [point.x for point in geoms]
    ys = [point.y for point in geoms]
    is_geographic = (
        min(xs) >= -180 and max(xs) <= 180 and min(ys) >= -90 and max(ys) <= 90
    )
    crs = "EPSG:4326" if is_geographic else "EPSG:32632"

    return gpd.GeoDataFrame({"bus_index": indices}, geometry=geoms, crs=crs)


def process_synthetic_grids(dbc: DatabaseClient, plz: int, output_dir: Path) -> pd.DataFrame:
    """Calculate and export comparison parameters for synthetic grids in one postcode area."""
    print(f"Processing synthetic grids for PLZ {plz}...")
    from pylovo.analysis.parameter_calculation import ParameterCalculator

    calc = ParameterCalculator()
    calc.dbc = dbc
    return export_synthetic_comparison_parameters_for_plz(calc, plz, output_dir=output_dir)


def process_real_grids(dbc: DatabaseClient, data_path: str, plz: int, output_dir: Path) -> pd.DataFrame:
    """Calculate and export comparison parameters for real LV JSON subnets."""
    print(f"Processing real grids from {data_path}...")

    buildings_gdf = _load_buildings_for_plz(dbc, plz)
    if buildings_gdf is None:
        return pd.DataFrame()

    from pylovo.analysis.parameter_calculation import ParameterCalculator

    metrics_list = []
    calc = ParameterCalculator()
    calc.dbc = dbc

    for file_path in iter_real_grid_files(data_path):
        try:
            net = pp.from_json(str(file_path))
            consumer_buses = _infer_real_grid_consumer_buses(net, buildings_gdf)

            params = compute_comparison_parameters(calc, net, consumer_buses=consumer_buses)
            params["grid_name"] = file_path.stem
            params["file_name"] = file_path.name
            metrics_list.append(params)
        except Exception as exc:
            print(f"Error processing real grid {file_path.name}: {exc}")

    if not metrics_list:
        return pd.DataFrame()

    df = pd.DataFrame(metrics_list)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "real_grid_metrics.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved real grid metrics to {csv_path}")
    return df


def run_grid_comparison(plz: int, output_dir: Path, data_path: str | None = None) -> None:
    """Run the full comparison workflow and write both metrics CSV files."""
    with DatabaseClient() as dbc:
        process_synthetic_grids(dbc, plz, output_dir)

        grid_data_path = Path(data_path) if data_path is not None else Path(GRID_DATA_PATH)
        if grid_data_path.exists():
            process_real_grids(dbc, str(grid_data_path), plz, output_dir)
        else:
            print(f"GRID_DATA_PATH not found or invalid: {grid_data_path}")


def _load_buildings_for_plz(dbc: DatabaseClient, plz: int) -> gpd.GeoDataFrame | None:
    """Load building geometries for the postcode area used in real-grid comparison fallback."""
    try:
        query = f"""
            SELECT br.osm_id, br.peak_load_in_kw, ST_AsText(br.geom) as wkt
            FROM buildings_result br
            JOIN grid_result gr ON br.grid_result_id = gr.grid_result_id
            WHERE gr.plz = {plz} AND br.version_id = '{VERSION_ID}'
        """
        buildings_df = pd.read_sql(query, dbc.sqla_engine)
    except Exception as exc:
        print(f"Error fetching buildings: {exc}")
        return None

    if buildings_df.empty:
        print("No buildings found for this PLZ.")
        return None

    buildings_df["geometry"] = buildings_df["wkt"].apply(wkt.loads)
    return gpd.GeoDataFrame(buildings_df, geometry="geometry", crs="EPSG:3035")


def _infer_real_grid_consumer_buses(net: pp.pandapowerNet, buildings_gdf: gpd.GeoDataFrame) -> list[int] | None:
    """Infer consumer buses for real grids when no explicit load buses are available."""
    if not net.load.empty:
        return net.load["bus"].unique().tolist()

    if "geo" not in net.bus.columns or not net.bus["geo"].notna().any():
        return None

    bus_gdf = extract_bus_geometries(net)
    if bus_gdf.empty:
        return None

    if buildings_gdf.crs is None:
        buildings_gdf = buildings_gdf.set_crs(epsg=3035, allow_override=True)

    if bus_gdf.crs.to_string() != buildings_gdf.crs.to_string():
        bus_gdf = bus_gdf.to_crs(buildings_gdf.crs)

    joined = gpd.sjoin_nearest(buildings_gdf, bus_gdf, distance_col="dist")
    print(f"DEBUG: Matched {len(joined)} buildings to buses.")
    return joined["bus_index"].dropna().astype(int).unique().tolist()


def _upsert_comparison_parameters(calculator: "ParameterCalculator", grid_result_id: int, params: dict) -> None:
    """Persist the comparison parameter subset needed by the historical grid_parameters table."""
    query = """
        INSERT INTO grid_parameters (grid_result_id, feeder_lines, house_connections, cable_length, avg_trafo_distance, max_voltage_drop)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (grid_result_id) DO UPDATE SET
        feeder_lines = EXCLUDED.feeder_lines,
        house_connections = EXCLUDED.house_connections,
        cable_length = EXCLUDED.cable_length,
        avg_trafo_distance = EXCLUDED.avg_trafo_distance,
        max_voltage_drop = EXCLUDED.max_voltage_drop;
    """
    calculator.dbc.cur.execute(
        query,
        (
            grid_result_id,
            params["feeder_lines"],
            params["house_connections"],
            params["cable_length"],
            params["avg_trafo_distance"],
            None,
        ),
    )


__all__ = [
    "export_synthetic_comparison_parameters_for_plz",
    "extract_bus_geometries",
    "iter_real_grid_files",
    "process_real_grids",
    "process_synthetic_grids",
    "run_grid_comparison",
]