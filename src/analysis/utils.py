"""
Shared utility functions for grid analysis.
Used by both core (synthetic) and validation (DSO) workflows.
"""

import pandas as pd
import pandapower as pp
from pathlib import Path
import yaml
import logging
from typing import Optional

# ============================================================================
# Configuration Management
# ============================================================================

# Configuration file path
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config_validation.yaml"


def load_validation_config() -> tuple[Path, str, str]:
    """Load validation configuration from config_validation.yaml.

    Returns:
        tuple[Path, str, str]: (data_dir, net_name, projection)

    Raises:
        FileNotFoundError: if the config file or data_dir is missing.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config_validation.yaml.template to config_validation.yaml "
            "and set data_dir (and optionally net_name, projection)."
        )

    # Read YAML config (empty file -> empty dict)
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    data_dir_raw = cfg.get("data_dir", "")
    if not data_dir_raw:
        raise FileNotFoundError(
            f"'data_dir' is empty in {CONFIG_PATH}. Please set an absolute path to your validation folder."
        )

    data_dir = Path(data_dir_raw).expanduser().resolve()
    if not data_dir.exists():
        raise FileNotFoundError(
            f"Configured data_dir does not exist: '{data_dir}'. Please set a valid path in {CONFIG_PATH}."
        )

    net_name = (cfg.get("net_name") or "").strip()
    projection = (cfg.get("projection") or "epsg:3035").strip()

    return data_dir, net_name, projection


def read_net_json() -> tuple[pp.pandapowerNet, str]:
    """Load pandapower network from configured JSON file.

    Returns:
        tuple: (net, file_path)
    """
    data_dir, net_name, _projection = load_validation_config()
    file_path = f"{data_dir}/{net_name}"
    json_path = f"{file_path}.json"
    net = pp.from_json(json_path)
    return net, file_path


# ============================================================================
# Logging
# ============================================================================

def create_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a configured logger instance.

    Args:
        name: Logger name
        log_file: Path to log file
        level: Logging level (default: logging.INFO)

    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name=name)
    logger.handlers.clear()  # Clear existing handlers to prevent duplication

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # to print log messages to a file
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    # to print log messages to console
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

def oneSimultaneousLoad(installed_power: float, load_count: int,
                        sim_factor: float) -> float:
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
    if not net.load.empty:
        # Create max_p_mw from p_mw if needed
        if 'max_p_mw' not in net.load.columns and 'p_mw' in net.load.columns:
            net.load['max_p_mw'] = net.load['p_mw']

        if 'max_p_mw' not in net.load.columns:
            net.load['max_p_mw'] = 0.0

        if 'name' not in net.load.columns:
            net.load['name'] = [f"Load_{i}" for i in net.load.index]


def normalize_bus_names(net: pp.pandapowerNet) -> None:
    """Ensure all buses have names.

    Uses chr_name if available, otherwise creates generic names.

    Args:
        net: pandapower network to normalize (modified in-place)
    """
    if 'name' not in net.bus.columns or net.bus['name'].isna().any():
        net.bus['name'] = net.bus.apply(
            lambda row: row.get('name') if pd.notna(row.get('name'))
                       else row.get('chr_name', f"Bus_{row.name}"),
            axis=1
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

