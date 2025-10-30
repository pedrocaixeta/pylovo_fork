"""
Network normalization utilities for external pandapower networks.
This module provides lightweight utilities to prepare external networks
(DSO data, benchmarks) for topology analysis by ensuring required
data structures exist.
The core logic here (zone inference) complements the network preparation
done in MetricsCalculator (parameter_calculation_swf.py). Use this module
for standalone network adaptation before passing to MetricsCalculator.
"""
import pandapower as pp
from typing import Optional, Dict
import logging
from src.analysis.validation.utils import (
    ensure_numeric_types,
    normalize_load_columns,
    normalize_bus_names,
    validate_network_structure
)
def detect_naming_convention(net: pp.pandapowerNet) -> str:
    """
    Detect network naming convention from bus/line names.
    Returns 'forchheim' if names match pattern like '1234567_*', else 'generic'.
    This is used to identify DSO-specific network formats.
    """
    for table in ["bus", "line", "load", "sgen"]:
        df = getattr(net, table, None)
        if df is None or len(df) == 0:
            continue
        # Check chr_name or name column
        col = "chr_name" if "chr_name" in df.columns else "name" if "name" in df.columns else None
        if not col:
            continue
        names = df[col].dropna().astype(str)
        if len(names) == 0:
            continue
        sample = names.iloc[0]
        if "_" in sample and sample.split("_")[0].isdigit():
            return "forchheim"
    return "generic"
def infer_bus_zones_from_load_patterns(net: pp.pandapowerNet, default_zone: str = 'Residential') -> None:
    """
    Infer bus zones from DSO load naming patterns.
    Recognizes patterns like:
    - NS_Last_* → Residential (low-voltage residential loads)
    - NS_EZA_* → Residential (typically residential PV generators)
    - MS_Last_* → Commercial (medium-voltage loads)
    Modifies net.bus['zone'] in-place.
    Parameters
    ----------
    net : pp.pandapowerNet
        Network to modify (in-place)
    default_zone : str
        Default zone for buses without recognizable patterns (default: 'Residential')
    """
    if 'zone' not in net.bus.columns:
        net.bus['zone'] = default_zone
    net.bus['zone'] = net.bus['zone'].fillna(default_zone)
    # Infer from load names if available
    if 'name' not in net.load.columns or net.load.empty:
        return
    for bus_idx in net.load['bus'].unique():
        if bus_idx not in net.bus.index:
            continue
        bus_loads = net.load[net.load['bus'] == bus_idx]
        load_names = bus_loads['name'].astype(str)
        # Check DSO patterns (most specific patterns first)
        if load_names.str.contains('NS_Last_', regex=False).any():
            net.bus.loc[bus_idx, 'zone'] = 'Residential'
        elif load_names.str.contains('NS_EZA_', regex=False).any():
            net.bus.loc[bus_idx, 'zone'] = 'Residential'
        elif load_names.str.contains('MS_Last_', regex=False).any():
            net.bus.loc[bus_idx, 'zone'] = 'Commercial'
    # Propagate zones from load.zone column if it exists
    if 'zone' in net.load.columns:
        for bus_idx in net.load['bus'].unique():
            if bus_idx not in net.bus.index:
                continue
            load_zones = net.load[net.load['bus'] == bus_idx]['zone'].mode()
            if len(load_zones) > 0 and net.bus.loc[bus_idx, 'zone'] == default_zone:
                net.bus.loc[bus_idx, 'zone'] = load_zones.iloc[0]
    # Ensure valid zones
    valid_zones = ['Residential', 'Commercial', 'Public']
    net.bus['zone'] = net.bus['zone'].apply(
        lambda z: z if z in valid_zones else default_zone
    )
def adapt_network(
    net: pp.pandapowerNet,
    zone_mapping: Optional[Dict[str, str]] = None,
    default_zone: str = 'Residential',
    validate: bool = True
) -> pp.pandapowerNet:
    """
    Prepare external DSO network for topology analysis.
    
    Performs complete network normalization:
    1. Convert data types (strings → floats)
    2. Ensure required columns exist (names, zones, max_p_mw)
    3. Infer bus zones from load naming patterns
    4. Apply custom zone mappings
    5. Validate network structure
    
    Modified in-place, also returned for convenience.
    
    Parameters
    ----------
    net : pp.pandapowerNet
        Network to adapt (modified in-place)
    zone_mapping : dict, optional
        Custom zone name mapping, e.g., {'residential': 'Residential'}
    default_zone : str
        Fallback zone (default: 'Residential')
    validate : bool
        Run structure validation (default: True)
    
    Returns
    -------
    pp.pandapowerNet
        The adapted network (same object)
    
    Examples
    --------
    >>> import pandapower as pp
    >>> from src.analysis.validation.network_adapter_swf import adapt_network
    >>> from src.analysis.validation.parameter_calculation_swf import ParameterCalculatorSWF
    >>> 
    >>> net = pp.from_json('dso_network.json')
    >>> net = adapt_network(net)
    >>> calc = ParameterCalculatorSWF()
    >>> metrics = calc.compute_metrics(net)
    """
    logger = logging.getLogger(__name__)
    # 1. Normalize data types (strings to floats, etc.)
    ensure_numeric_types(net)
    # 2. Ensure required columns exist
    normalize_bus_names(net)
    normalize_load_columns(net)
    # 3. Infer bus zones from load patterns (DSO-specific)
    infer_bus_zones_from_load_patterns(net, default_zone=default_zone)
    # 4. Apply zone mapping if provided
    if zone_mapping and 'zone' in net.bus.columns:
        net.bus['zone'] = net.bus['zone'].replace(zone_mapping)
    # 5. Remove zone from loads (should only be on buses to avoid merge conflicts)
    if 'zone' in net.load.columns:
        net.load.drop('zone', axis=1, inplace=True)
    # 6. Validate if requested
    if validate:
        issues = validate_network_structure(net)
        for issue in issues:
            if "transformer" in issue.lower():
                raise ValueError(f"Critical network issue: {issue}")
            logger.warning(issue)
    logger.info(f"Network adapted: {len(net.bus)} buses, {len(net.load)} loads, {len(net.line)} lines")
    return net
