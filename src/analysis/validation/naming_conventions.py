"""
Naming convention parsers for different DSO network formats.

Supports:
- SWF hierarchical naming convention (underscore-separated)
- Forchheim naming convention (continuous numeric string)
- Generic bus type detection
"""

import pandas as pd
import pandapower as pp
from typing import Dict, Optional
import logging


# ============================================================================
# SWF Naming Convention Parser
# ============================================================================

def parse_SWF_chr_name(chr_name: str) -> Dict[str, str]:
    """
    Parse SWF hierarchical naming convention.

    Structure:
    Position 1: Netzebene (voltage level) - 1=HöS ... 7=NS(LV)
    Position 2-3: Netznummer (network identifier)
    Position 4-5: SS-Nummer (substation number)
    Position 6-7: Strangnummer (branch number)
    Position 8-13: Hauptknoten 1 + 2 (main nodes, 2x3 digits)
    Position 14-19: Optional repetition
    Position 20-25: Further connections
    Position 26-27: Objekttyp (object type)
    Position 28-30: Objektnummer (object number)

    Parameters
    ----------
    chr_name : str
        The chr_name string to parse

    Returns
    -------
    dict
        Parsed components with keys: netzebene, netznummer, ss_nummer,
        strangnummer, hauptknoten_1, hauptknoten_2, objekttyp, objektnummer
    """
    name_str = str(chr_name)

    # Remove any underscores if present (some networks may have them)
    name_str = name_str.replace('_', '')

    if len(name_str) < 13:
        return {}

    try:
        result = {
            'netzebene': name_str[0:1],  # Position 1
            'netznummer': name_str[1:3],  # Position 2-3
            'ss_nummer': name_str[3:5],   # Position 4-5
            'strangnummer': name_str[5:7], # Position 6-7
            'hauptknoten_1': name_str[7:10],  # Position 8-10
            'hauptknoten_2': name_str[10:13], # Position 11-13
        }

        # Optional fields if string is long enough
        if len(name_str) >= 19:
            result['optional_rep_1'] = name_str[13:16]
            result['optional_rep_2'] = name_str[16:19]

        if len(name_str) >= 25:
            result['further_conn_1'] = name_str[19:22]
            result['further_conn_2'] = name_str[22:25]

        if len(name_str) >= 27:
            result['objekttyp'] = name_str[25:27]

        if len(name_str) >= 30:
            result['objektnummer'] = name_str[27:30]

        # Grid identifier (for splitting): Netzebene + Netznummer + SS-Nummer
        result['grid_id'] = name_str[0:5]

        return result

    except Exception:
        return {}


def get_SWF_object_type_name(objekttyp_code: str) -> str:
    """
    Get object type name from SWF code.

    Object Type Codes:
    01 = Knoten (node)
    02 = US-SS (substation)
    03 = Verzweigung (branch/junction)
    04 = Externes Netz (external grid)
    05 = Trafo (transformer)
    06 = Leitung (line/cable)
    07 = Schalter (switch)
    08 = Last (load)
    09 = EZA (generator)
    10 = Feld (field)
    11 = Schalter intern (internal switch)
    """
    type_map = {
        '01': 'Knoten',
        '02': 'Substation',
        '03': 'Junction',
        '04': 'External_Grid',
        '05': 'Transformer',
        '06': 'Line',
        '07': 'Switch',
        '08': 'Load',
        '09': 'Generator',
        '10': 'Field',
        '11': 'Internal_Switch',
    }
    return type_map.get(str(objekttyp_code).zfill(2), 'Unknown')


def enhance_network_with_SWF_info(net: pp.pandapowerNet) -> pp.pandapowerNet:
    """
    Enhance network with parsed SWF naming information.

    Adds columns to bus/load/line tables with parsed chr_name components.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network with SWF chr_name structure

    Returns
    -------
    pp.pandapowerNet
        Network with additional columns
    """
    logger = logging.getLogger(__name__)

    # Parse bus names
    if 'chr_name' in net.bus.columns:
        logger.info("Parsing bus chr_names...")
        parsed = net.bus['chr_name'].apply(parse_SWF_chr_name)

        # Add parsed columns
        for key in ['netzebene', 'netznummer', 'ss_nummer', 'strangnummer',
                    'hauptknoten_1', 'hauptknoten_2', 'objekttyp', 'grid_id']:
            if parsed.apply(lambda x: key in x).any():
                net.bus[f'SWF_{key}'] = parsed.apply(lambda x: x.get(key, ''))

        # Add object type name if objekttyp exists
        if 'SWF_objekttyp' in net.bus.columns:
            net.bus['SWF_object_type'] = net.bus['SWF_objekttyp'].apply(get_SWF_object_type_name)

        logger.info(f"Enhanced {len(net.bus)} buses with SWF naming info")

    # Parse load names if they have chr_name
    if not net.load.empty and 'chr_name' in net.load.columns:
        logger.info("Parsing load chr_names...")
        parsed = net.load['chr_name'].apply(parse_SWF_chr_name)

        for key in ['objekttyp', 'grid_id']:
            if parsed.apply(lambda x: key in x).any():
                net.load[f'SWF_{key}'] = parsed.apply(lambda x: x.get(key, ''))

        if 'SWF_objekttyp' in net.load.columns:
            net.load['SWF_object_type'] = net.load['SWF_objekttyp'].apply(get_SWF_object_type_name)

    # Lines get their info from connected buses
    if not net.line.empty:
        logger.info("Enhancing lines with bus information...")
        # Add grid_id from from_bus
        net.line['from_bus_grid_id'] = net.line['from_bus'].map(
            net.bus['SWF_grid_id'] if 'SWF_grid_id' in net.bus.columns else pd.Series()
        )
        net.line['to_bus_grid_id'] = net.line['to_bus'].map(
            net.bus['SWF_grid_id'] if 'SWF_grid_id' in net.bus.columns else pd.Series()
        )

    return net


# ============================================================================
# Forchheim Naming Convention Parser
# ============================================================================

def parse_forchheim_chr_name(chr_name: str) -> Dict[str, str]:
    """
    Parse Forchheim naming convention (continuous numeric string).

    Structure (30 digits total):
    Position 1: Netzebene (voltage level) - 1=HöS ... 7=NS(LV)
    Position 2-3: Netznummer (network identifier)
    Position 4-5: SS-Nummer (substation number)
    Position 6-7: Strangnummer (branch number)
    Position 8-13: Hauptknoten 1 + 2 (main nodes, 2x3 digits)
    Position 14-19: Optional repetition
    Position 20-25: Further connections
    Position 26-27: Objekttyp (object type)
    Position 28-30: Objektnummer (object number)

    Parameters
    ----------
    chr_name : str
        The chr_name string to parse

    Returns
    -------
    dict
        Parsed components
    """
    name_str = str(chr_name).strip()

    if len(name_str) < 13:
        return {}

    try:
        result = {
            'netzebene': name_str[0:1],
            'netznummer': name_str[1:3],
            'ss_nummer': name_str[3:5],
            'strangnummer': name_str[5:7],
            'hauptknoten_1': name_str[7:10],
            'hauptknoten_2': name_str[10:13],
        }

        if len(name_str) >= 19:
            result['optional_rep_1'] = name_str[13:16]
            result['optional_rep_2'] = name_str[16:19]

        if len(name_str) >= 25:
            result['further_conn_1'] = name_str[19:22]
            result['further_conn_2'] = name_str[22:25]

        if len(name_str) >= 27:
            result['objekttyp'] = name_str[25:27]

        if len(name_str) >= 30:
            result['objektnummer'] = name_str[27:30]

        # Grid identifier for splitting
        result['grid_id'] = name_str[0:7]  # Netzebene + Netznummer + SS-Nummer + Strangnummer

        return result

    except Exception:
        return {}


def get_forchheim_object_type_name(objekttyp_code: str) -> str:
    """
    Get object type name from Forchheim code.

    Uses the same codes as SWF convention.
    """
    return get_SWF_object_type_name(objekttyp_code)


# ============================================================================
# Auto-detection and Generic Functions
# ============================================================================

def detect_naming_convention(net: pp.pandapowerNet) -> str:
    """
    Auto-detect the naming convention used in a network.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network to analyze

    Returns
    -------
    str
        One of: 'SWF', 'forchheim', 'generic'
    """
    if 'chr_name' not in net.bus.columns:
        return 'generic'

    # Sample a few chr_names
    sample_names = net.bus['chr_name'].dropna().head(10).tolist()

    if not sample_names:
        return 'generic'

    # Check for SWF pattern (contains underscores)
    if any('_' in str(name) for name in sample_names):
        return 'SWF'

    # Check for Forchheim pattern (all numeric, specific length)
    if all(str(name).replace('_', '').isdigit() for name in sample_names):
        avg_length = sum(len(str(name).replace('_', '')) for name in sample_names) / len(sample_names)
        if 25 <= avg_length <= 32:
            return 'forchheim'

    return 'generic'


def identify_bus_type_generic(net: pp.pandapowerNet, bus_idx: int) -> str:
    """
    Identify bus type using generic heuristics (no naming convention).

    Parameters
    ----------
    net : pp.pandapowerNet
        The network
    bus_idx : int
        Bus index to classify

    Returns
    -------
    str
        One of: 'lv_bus', 'consumer_bus', 'connection_bus'
    """
    # Check if it's a transformer LV bus
    if not net.trafo.empty:
        if bus_idx in net.trafo['lv_bus'].values:
            return 'lv_bus'

    # Check if it has loads (consumer bus)
    if not net.load.empty:
        if bus_idx in net.load['bus'].values:
            return 'consumer_bus'

    # Otherwise, it's an internal connection bus
    return 'connection_bus'


def identify_bus_types_in_network(net: pp.pandapowerNet,
                                  naming_convention: str = 'auto') -> None:
    """
    Identify and label bus types for a network.

    Adds standardized bus name patterns for compatibility with
    topology_analysis.ParameterCalculator.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network to process (modified in-place)
    naming_convention : str
        One of: 'auto', 'SWF', 'forchheim', 'generic'
    """
    logger = logging.getLogger(__name__)

    if naming_convention == 'auto':
        naming_convention = detect_naming_convention(net)

    logger.info(f"Identifying bus types using '{naming_convention}' convention")

    # Identify LV bus (transformer LV side)
    if not net.trafo.empty:
        lv_bus = net.trafo.iloc[0]['lv_bus']
        if lv_bus in net.bus.index:
            current_name = str(net.bus.loc[lv_bus, 'name'])
            if 'LVbus' not in current_name:
                net.bus.loc[lv_bus, 'name'] = f"LVbus_{lv_bus}"

    # Mark consumer buses (with loads)
    if not net.load.empty:
        consumer_buses = net.load['bus'].unique()
        for bus_idx in consumer_buses:
            if bus_idx in net.bus.index:
                current_name = str(net.bus.loc[bus_idx, 'name'])
                if 'Consumer' not in current_name and 'LVbus' not in current_name:
                    net.bus.loc[bus_idx, 'name'] = f"Consumer Nodebus_{bus_idx}"

    # Mark connection buses (internal buses)
    lv_bus = net.trafo.iloc[0]['lv_bus'] if not net.trafo.empty else None
    consumer_buses = set(net.load['bus'].unique()) if not net.load.empty else set()

    for bus_idx in net.bus.index:
        current_name = str(net.bus.loc[bus_idx, 'name'])
        if (bus_idx != lv_bus and
            bus_idx not in consumer_buses and
            'LVbus' not in current_name and
            'Consumer' not in current_name and
            'Connection' not in current_name):
            net.bus.loc[bus_idx, 'name'] = f"Connection Nodebus_{bus_idx}"

    logger.debug(f"Bus types identified for {len(net.bus)} buses")

