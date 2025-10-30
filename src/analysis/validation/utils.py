"""
Shared utility functions for grid analysis.
Used by both core (synthetic) and validation (DSO) workflows.
"""

import os
import logging
from pathlib import Path
from typing import List

import pandas as pd
import pandapower as pp
from dotenv import load_dotenv, find_dotenv

# ============================================================================
# Configuration Management (.env-based)
# ============================================================================

# Project root (repository root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Load .env once (from repo root if present)
load_dotenv(find_dotenv(), override=True)


def _resolve_data_dir(p: str | os.PathLike) -> Path:
    """Resolve GRID_DATA_PATH to an absolute Path.

    Rules:
    - If path starts with "/src/", treat it as project-relative (join with PROJECT_ROOT)
    - If path is absolute (e.g., "/home/user/..."), use as-is
    - Otherwise, treat as project-relative
    Also normalizes and checks existence.
    """
    if p is None:
        raise FileNotFoundError("Environment variable GRID_DATA_PATH is not set. Please define it in your .env.")

    s = str(p).strip()
    if not s:
        raise FileNotFoundError("Environment variable GRID_DATA_PATH is empty. Please set a valid directory path.")

    # Normalize project-relative prefix like "/src/..."
    if s.startswith("/src/"):
        path = PROJECT_ROOT / s.lstrip("/")
    else:
        path = Path(s)
        if not path.is_absolute():
            path = PROJECT_ROOT / path

    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Configured GRID_DATA_PATH does not exist: '{path}'")
    if not path.is_dir():
        raise NotADirectoryError(f"GRID_DATA_PATH must be a directory, got: '{path}'")
    return path


def load_validation_config() -> tuple[Path, str, str]:
    """Load validation configuration from environment variables.

    Reads the following environment variables (from .env):
      - GRID_DATA_PATH: Directory containing the grid dataset (e.g., src/analysis/grid_data/SWF_V7)
      - NET_NAME: Base filename of the network (e.g., SWF_V7)
      - PROJECTION (optional): EPSG code of the source CRS (default: epsg:25832)

    Returns:
        tuple[Path, str, str]: (data_dir, net_name, projection)

    Raises:
        FileNotFoundError / ValueError with actionable messages when misconfigured.
    """
    data_dir_env = os.getenv("GRID_DATA_PATH")
    net_name = (os.getenv("NET_NAME") or "").strip()
    projection = (os.getenv("PROJECTION") or "epsg:25832").strip()

    data_dir = _resolve_data_dir(data_dir_env)

    if not net_name:
        # If not provided, infer from directory name (e.g., .../SWF_V7 -> SWF_V7)
        net_name = data_dir.name

    return data_dir, net_name, projection


def read_net_json(
    subgrid_file: str | Path | None = None,
    allow_multi: bool = False,
) -> tuple[pp.pandapowerNet | List[pp.pandapowerNet], str]:
    """Load pandapower network from configured JSON file, or a specific subgrid.

    Parameters
    ----------
    subgrid_file : str | Path | None
        Name of a subgrid JSON inside <DATA_DIR>/subgrids. If provided, loads that file.
        Examples: "041__trafo_105.json" or "041__trafo_105" (".json" suffix optional).
        If None (default), loads the main <NET_NAME>.json in <DATA_DIR>.
    allow_multi : bool
        If True and the main JSON is a multi-net container (list/dict), returns a list of nets.
        If False (default), attempts to load a single pandapower net as before.

    Returns
    -------
    (net_or_list, file_base)
        net_or_list: A single pandapowerNet or a list of pandapowerNets when allow_multi=True.
        file_base:   The base path (without .json extension) of the loaded file as string.
    """
    data_dir, net_name, _ = load_validation_config()

    # Subgrid-specific load
    if subgrid_file is not None:
        name = str(subgrid_file)
        if not name.endswith(".json"):
            name += ".json"
        json_path = (data_dir / "subgrids" / name).resolve()
        if not json_path.exists():
            raise FileNotFoundError(f"Subgrid JSON not found: {json_path}")
        net = pp.from_json(str(json_path))
        return net, str(json_path.with_suffix(""))

    # Default: load main NET_NAME.json
    main_base = data_dir / net_name
    main_json = main_base.with_suffix(".json")
    if not main_json.exists():
        raise FileNotFoundError(
            f"Network JSON not found: {main_json}. Ensure NET_NAME ('{net_name}') matches the file in {data_dir}."
        )

    net = pp.from_json(str(main_json))
    return net, str(main_base)


# ============================================================================
# Logging
# ============================================================================

def create_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a configured logger instance."""
    logger = logging.getLogger(name=name)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(level)
    logger.propagate = False

    return logger


# ============================================================================
# Load Calculations (from src/utils.py)
# ============================================================================

def oneSimultaneousLoad(installed_power: float, load_count: int, sim_factor: float) -> float:
    """Calculate simultaneous load using simultaneity factor.

    Based on Kerber 2011, Equation 3.2, Page 23.
    Used in both topology analysis and validation workflows.

    Args:
        installed_power: Total installed power (kW or MW)
        load_count: Number of loads/consumers
        sim_factor: Simultaneity factor (g_inf)

    Returns:
        float: Simultaneous peak load in same unit as installed_power
    """
    if isinstance(load_count, int):
        if load_count == 0:
            return 0.0

    sim_load = installed_power * (sim_factor + (1 - sim_factor) * (load_count ** (-3 / 4)))
    return sim_load


# ============================================================================
# Network Data Type Normalization
# ============================================================================

def ensure_numeric_types(net: pp.pandapowerNet) -> None:
    """Ensure all numeric columns in network tables are proper numeric types.

    DSO/external data often has numeric values stored as strings.
    This converts them to proper float/int types.

    Args:
        net: pandapower network to normalize (modified in-place)
    """
    logger = logging.getLogger(__name__)

    # Bus numeric columns
    bus_numeric = ['vn_kv', 'min_vm_pu', 'max_vm_pu']
    for col in bus_numeric:
        if col in net.bus.columns:
            net.bus[col] = pd.to_numeric(net.bus[col], errors='coerce')

    # Line numeric columns
    line_numeric = ['length_km', 'r_ohm_per_km', 'x_ohm_per_km', 'c_nf_per_km',
                    'g_us_per_km', 'max_i_ka', 'df']
    for col in line_numeric:
        if col in net.line.columns:
            net.line[col] = pd.to_numeric(net.line[col], errors='coerce')

    # Transformer numeric columns
    trafo_numeric = ['sn_mva', 'vn_hv_kv', 'vn_lv_kv', 'vk_percent', 'vkr_percent',
                     'pfe_kw', 'i0_percent', 'shift_degree']
    for col in trafo_numeric:
        if col in net.trafo.columns:
            net.trafo[col] = pd.to_numeric(net.trafo[col], errors='coerce')

    # Load numeric columns
    if not net.load.empty:
        load_numeric = ['p_mw', 'q_mvar', 'max_p_mw', 'scaling']
        for col in load_numeric:
            if col in net.load.columns:
                net.load[col] = pd.to_numeric(net.load[col], errors='coerce').fillna(0.0)

    # Sgen numeric columns if present
    if not net.sgen.empty:
        sgen_numeric = ['p_mw', 'q_mvar', 'sn_mva', 'scaling']
        for col in sgen_numeric:
            if col in net.sgen.columns:
                net.sgen[col] = pd.to_numeric(net.sgen[col], errors='coerce')

    logger.debug("Converted numeric columns to proper types")


def normalize_load_columns(net: pp.pandapowerNet) -> None:
    """Ensure loads have required columns (max_p_mw, name).

    Args:
        net: pandapower network to normalize (modified in-place)
    """
    # Always ensure max_p_mw column exists (even for empty load table)
    if 'max_p_mw' not in net.load.columns:
        if not net.load.empty and 'p_mw' in net.load.columns:
            net.load['max_p_mw'] = net.load['p_mw']
        else:
            net.load['max_p_mw'] = pd.Series(dtype=float)

    # Ensure name column exists
    if 'name' not in net.load.columns:
        if not net.load.empty:
            net.load['name'] = [f"Load_{i}" for i in net.load.index]
        else:
            net.load['name'] = pd.Series(dtype=str)


def normalize_bus_names(net: pp.pandapowerNet) -> None:
    """Ensure all buses have names.

    Uses chr_name if available, otherwise creates generic names.

    Args:
        net: pandapower network to normalize (modified in-place)
    """
    if 'name' not in net.bus.columns or net.bus['name'].isna().any():
        net.bus['name'] = net.bus.apply(
            lambda row: row.get('name') if pd.notna(row.get('name')) else row.get('chr_name', f"Bus_{row.name}"),
            axis=1,
        )


# ============================================================================
# Network Validation
# ============================================================================

def validate_network_structure(net: pp.pandapowerNet) -> list[str]:
    """Validate that a network has minimum required structure.

    Args:
        net: pandapower network to validate

    Returns:
        list[str]: List of warning/error messages (empty if valid)
    """
    issues = []

    if net.trafo.empty:
        issues.append("Network has no transformers")

    if net.load.empty:
        issues.append("Network has no loads")

    if net.line.empty:
        issues.append("Network has no lines")

    if net.bus.empty:
        issues.append("Network has no buses")

    return issues


# ============================================================================
# Display/Formatting Helpers
# ============================================================================

def format_metrics_summary(params: dict) -> str:
    """Format metrics dictionary as readable summary text.

    Args:
        params: Dictionary of computed metrics

    Returns:
        str: Formatted summary text
    """
    summary = []
    summary.append("=" * 80)
    summary.append("NETWORK METRICS SUMMARY")
    summary.append("=" * 80)

    summary.append("\nTopology:")
    summary.append(f"  • Branches: {params.get('no_branches', 'N/A')}")
    summary.append(f"  • House connections: {params.get('no_house_connections', 'N/A')}")
    summary.append(f"  • Connection buses: {params.get('no_connection_buses', 'N/A')}")
    summary.append(f"  • House connections per branch: {params.get('no_house_connections_per_branch', 'N/A'):.2f}")

    summary.append("\nLoad Characteristics:")
    summary.append(f"  • Number of households: {params.get('no_households', 'N/A')}")
    summary.append(f"  • Household equivalents: {params.get('no_household_equ', 'N/A'):.2f}")
    summary.append(f"  • Households per branch: {params.get('no_households_per_branch', 'N/A'):.2f}")
    summary.append(f"  • Max households on a branch: {params.get('max_no_of_households_of_a_branch', 'N/A'):.2f}")
    summary.append(f"  • Max power (MW): {params.get('max_power_mw', 'N/A'):.3f}")
    summary.append(f"  • Simultaneous peak load (MW): {params.get('simultaneous_peak_load_mw', 'N/A'):.3f}")

    summary.append("\nSpatial Metrics:")
    summary.append(f"  • Average house distance (km): {params.get('house_distance_km', 'N/A'):.3f}")
    summary.append(f"  • Average trafo distance (km): {params.get('avg_trafo_dis', 'N/A'):.3f}")
    summary.append(f"  • Max trafo distance (km): {params.get('max_trafo_dis', 'N/A'):.3f}")
    summary.append(f"  • Cable length (km): {params.get('cable_length_km', 'N/A'):.3f}")
    summary.append(f"  • Cable length per house (km): {params.get('cable_len_per_house', 'N/A'):.3f}")

    summary.append("\nTransformer:")
    summary.append(f"  • Transformer rating (MVA): {params.get('transformer_mva', 'N/A'):.3f}")

    summary.append("\nElectrical Characteristics:")
    summary.append(f"  • Resistance (Ω·HE): {params.get('resistance', 'N/A'):.2f}")
    summary.append(f"  • Reactance (Ω·HE): {params.get('reactance', 'N/A'):.2f}")
    summary.append(f"  • R/X ratio: {params.get('ratio', 'N/A'):.2f}")
    summary.append(f"  • VSW per branch: {params.get('vsw_per_branch', 'N/A'):.2f}")
    summary.append(f"  • Max VSW of a branch: {params.get('max_vsw_of_a_branch', 'N/A'):.2f}")

    return "\n".join(summary)


def format_multi_grid_summary(results: list[dict]) -> str:
    """Format multi-grid analysis results as summary.

    Args:
        results: List of metrics dictionaries

    Returns:
        str: Formatted summary text
    """
    df = pd.DataFrame(results)

    summary = []
    summary.append("=" * 80)
    summary.append("MULTI-GRID ANALYSIS SUMMARY")
    summary.append("=" * 80)
    summary.append(f"\nNumber of grids analyzed: {len(results)}")

    summary.append("\nTopology Statistics:")
    summary.append(f"  • Branches per grid: {df['no_branches'].mean():.1f} ± {df['no_branches'].std():.1f}")
    summary.append(f"  • House connections per grid: {df['no_house_connections'].mean():.1f} ± {df['no_house_connections'].std():.1f}")

    summary.append("\nLoad Statistics:")
    summary.append(f"  • Households per grid: {df['no_households'].mean():.1f} ± {df['no_households'].std():.1f}")
    summary.append(f"  • Max power per grid (MW): {df['max_power_mw'].mean():.3f} ± {df['max_power_mw'].std():.3f}")

    summary.append("\nSpatial Statistics:")
    summary.append(f"  • Cable length per grid (km): {df['cable_length_km'].mean():.2f} ± {df['cable_length_km'].std():.2f}")
    summary.append(f"  • Max trafo distance (km): {df['max_trafo_dis'].mean():.3f} ± {df['max_trafo_dis'].std():.3f}")

    summary.append("\nTransformer Statistics:")
    summary.append(f"  • Transformer rating (MVA): {df['transformer_mva'].mean():.3f} ± {df['transformer_mva'].std():.3f}")

    summary.append("\nTotal across all grids:")
    summary.append(f"  • Total households: {df['no_households'].sum()}")
    summary.append(f"  • Total cable length (km): {df['cable_length_km'].sum():.2f}")
    summary.append(f"  • Total max power (MW): {df['max_power_mw'].sum():.3f}")

    return "\n".join(summary)

