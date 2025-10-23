"""
Enhanced data adapter for SWD networks with hierarchical naming convention.

This module provides functions to parse the SWD chr_name structure and extract
network topology and element information.
"""

import pandas as pd
import pandapower as pp
from typing import Dict, Tuple
import logging


def parse_swd_chr_name(chr_name: str) -> Dict[str, str]:
    """
    Parse SWD hierarchical naming convention.

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


def get_object_type_name(objekttyp_code: str) -> str:
    """
    Get object type name from code.

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


def enhance_network_with_swd_info(net: pp.pandapowerNet) -> pp.pandapowerNet:
    """
    Enhance network with parsed SWD naming information.

    Adds columns to bus/load/line tables with parsed chr_name components.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network with SWD chr_name structure

    Returns
    -------
    pp.pandapowerNet
        Network with additional columns
    """
    logger = logging.getLogger(__name__)

    # Parse bus names
    if 'chr_name' in net.bus.columns:
        logger.info("Parsing bus chr_names...")
        parsed = net.bus['chr_name'].apply(parse_swd_chr_name)

        # Add parsed columns
        for key in ['netzebene', 'netznummer', 'ss_nummer', 'strangnummer',
                    'hauptknoten_1', 'hauptknoten_2', 'objekttyp', 'grid_id']:
            if parsed.apply(lambda x: key in x).any():
                net.bus[f'swd_{key}'] = parsed.apply(lambda x: x.get(key, ''))

        # Add object type name if objekttyp exists
        if 'swd_objekttyp' in net.bus.columns:
            net.bus['swd_object_type'] = net.bus['swd_objekttyp'].apply(get_object_type_name)

        logger.info(f"Enhanced {len(net.bus)} buses with SWD naming info")

    # Parse load names if they have chr_name
    if not net.load.empty and 'chr_name' in net.load.columns:
        logger.info("Parsing load chr_names...")
        parsed = net.load['chr_name'].apply(parse_swd_chr_name)

        for key in ['objekttyp', 'grid_id']:
            if parsed.apply(lambda x: key in x).any():
                net.load[f'swd_{key}'] = parsed.apply(lambda x: x.get(key, ''))

        if 'swd_objekttyp' in net.load.columns:
            net.load['swd_object_type'] = net.load['swd_objekttyp'].apply(get_object_type_name)

    # Lines get their info from connected buses
    if not net.line.empty:
        logger.info("Enhancing lines with bus information...")
        # Add grid_id from from_bus
        net.line['from_bus_grid_id'] = net.line['from_bus'].map(
            net.bus['swd_grid_id'] if 'swd_grid_id' in net.bus.columns else pd.Series()
        )
        net.line['to_bus_grid_id'] = net.line['to_bus'].map(
            net.bus['swd_grid_id'] if 'swd_grid_id' in net.bus.columns else pd.Series()
        )

    return net


def adapt_swd_network_for_analysis(
    net: pp.pandapowerNet,
    default_zone: str = 'Residential'
) -> pp.pandapowerNet:
    """
    Adapt SWD network for parameter calculation and analysis.

    This function:
    1. Parses SWD naming convention
    2. Normalizes structure for analysis functions
    3. Ensures required columns exist

    Parameters
    ----------
    net : pp.pandapowerNet
        SWD network to adapt
    default_zone : str
        Default zone for loads

    Returns
    -------
    pp.pandapowerNet
        Adapted network ready for analysis
    """
    import copy
    logger = logging.getLogger(__name__)

    # Create deep copy
    adapted_net = copy.deepcopy(net)

    # Parse SWD naming convention
    if 'chr_name' in adapted_net.bus.columns:
        logger.info("Detected SWD network with chr_name convention")
        adapted_net = enhance_network_with_swd_info(adapted_net)

    # Convert all numeric columns to proper types (SWD data may have strings)
    _ensure_numeric_types(adapted_net)

    # Normalize load columns
    if not adapted_net.load.empty:
        # Ensure numeric columns are actually numeric (SWD data may have strings)
        numeric_load_cols = ['p_mw', 'q_mvar', 'max_p_mw', 'scaling']
        for col in numeric_load_cols:
            if col in adapted_net.load.columns:
                adapted_net.load[col] = pd.to_numeric(adapted_net.load[col], errors='coerce').fillna(0.0)

        if 'max_p_mw' not in adapted_net.load.columns and 'p_mw' in adapted_net.load.columns:
            adapted_net.load['max_p_mw'] = adapted_net.load['p_mw']
            logger.info("Created 'max_p_mw' from 'p_mw'")

        if 'max_p_mw' not in adapted_net.load.columns:
            adapted_net.load['max_p_mw'] = 0.0
            logger.warning("No power data in loads, set max_p_mw to 0")

        if 'name' not in adapted_net.load.columns:
            adapted_net.load['name'] = [f"Load_{i}" for i in adapted_net.load.index]

    # Ensure bus names exist
    if 'name' not in adapted_net.bus.columns or adapted_net.bus['name'].isna().any():
        adapted_net.bus['name'] = adapted_net.bus.apply(
            lambda row: row.get('name') if pd.notna(row.get('name')) else
                       row.get('chr_name', f"Bus_{row.name}"),
            axis=1
        )

    # Add zones for simultaneity factor calculation
    if 'zone' not in adapted_net.bus.columns:
        adapted_net.bus['zone'] = default_zone
    adapted_net.bus['zone'] = adapted_net.bus['zone'].fillna(default_zone)

    # Ensure zones are valid
    valid_zones = ['Residential', 'Commercial', 'Public']
    adapted_net.bus['zone'] = adapted_net.bus['zone'].apply(
        lambda z: z if z in valid_zones else default_zone
    )

    # Remove zone from loads if it exists (it should come from bus table)
    if 'zone' in adapted_net.load.columns:
        adapted_net.load.drop('zone', axis=1, inplace=True)

    # Identify bus types using SWD info or heuristics
    _identify_bus_types_swd(adapted_net)

    logger.info(f"Adapted SWD network: {len(adapted_net.bus)} buses, "
               f"{len(adapted_net.load)} loads, {len(adapted_net.line)} lines")

    return adapted_net


def _ensure_numeric_types(net: pp.pandapowerNet) -> None:
    """
    Ensure all numeric columns in the network are actually numeric types.
    
    SWD data may have numeric values stored as strings, which causes
    type errors in calculations.
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
    
    # Load numeric columns (done separately in adapt function)
    # Sgen numeric columns if present
    if not net.sgen.empty:
        sgen_numeric = ['p_mw', 'q_mvar', 'sn_mva', 'scaling']
        for col in sgen_numeric:
            if col in net.sgen.columns:
                net.sgen[col] = pd.to_numeric(net.sgen[col], errors='coerce')
    
    logger.debug("Converted numeric columns to proper types")


def _identify_bus_types_swd(net: pp.pandapowerNet) -> None:
    """
    Identify and label bus types for SWD networks.

    Uses SWD object type codes where available, otherwise uses heuristics.
    """
    logger = logging.getLogger(__name__)

    # Use SWD object type if available
    if 'swd_object_type' in net.bus.columns:
        # Buses with type 'Substation' or transformer LV bus -> LVbus
        if not net.trafo.empty:
            for idx, trafo in net.trafo.iterrows():
                lv_bus = trafo['lv_bus']
                if lv_bus in net.bus.index:
                    current_name = str(net.bus.loc[lv_bus, 'name'])
                    if 'LVbus' not in current_name:
                        net.bus.loc[lv_bus, 'name'] = f"LVbus_{lv_bus}"
    else:
        # Fallback: use heuristics
        if not net.trafo.empty:
            lv_bus = net.trafo.iloc[0]['lv_bus']
            if 'LVbus' not in str(net.bus.loc[lv_bus, 'name']):
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

    logger.debug("Bus types identified for SWD network")

