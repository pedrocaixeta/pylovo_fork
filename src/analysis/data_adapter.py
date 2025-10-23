"""
Data adapter for external pandapower networks.

This module provides adapters to normalize external pandapower networks (e.g., from DSO)
to match the structure expected by the topology analysis functions.
"""

import pandas as pd
import pandapower as pp
from typing import Optional, Dict, Any
import logging


class PandapowerNetworkAdapter:
    """
    Adapter to normalize external pandapower networks for topology analysis.

    This adapter ensures that external networks (e.g., from DSO) have the required
    structure (bus naming conventions, zones, etc.) for compatibility with the
    ParameterCalculator without modifying the original analysis code.
    """

    def __init__(
        self,
        net: pp.pandapowerNet,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the adapter with a pandapower network.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to adapt
        config : dict, optional
            Configuration for bus identification. Keys:
            - 'lv_bus_pattern': Pattern to identify LV bus (default: detect from trafo)
            - 'consumer_bus_pattern': Pattern to identify consumer buses (default: infer from loads)
            - 'connection_bus_pattern': Pattern to identify connection buses (default: infer)
            - 'default_zone': Default zone for loads without zone info (default: 'Residential')
            - 'zone_mapping': Dict to map existing zones to standard zones
        """
        self.original_net = net
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

    def adapt(self) -> pp.pandapowerNet:
        """
        Create an adapted copy of the network with normalized structure.

        Returns
        -------
        pp.pandapowerNet
            Adapted network with standardized naming and zones
        """
        # Create a deep copy to avoid modifying the original
        adapted_net = self._deep_copy_net(self.original_net)

        # Apply adaptations
        self._normalize_load_columns(adapted_net)
        self._ensure_bus_names(adapted_net)
        self._ensure_bus_zones(adapted_net)
        self._ensure_load_zones(adapted_net)
        self._validate_network(adapted_net)

        return adapted_net

    def _deep_copy_net(self, net: pp.pandapowerNet) -> pp.pandapowerNet:
        """Create a deep copy of the pandapower network."""
        import copy
        return copy.deepcopy(net)

    def _normalize_load_columns(self, net: pp.pandapowerNet) -> None:
        """
        Normalize load columns to match expected conventions.

        DSO data often uses 'p_mw' while synthetic grids use 'max_p_mw'.
        This method ensures 'max_p_mw' exists.
        """
        if not net.load.empty:
            # If max_p_mw doesn't exist but p_mw does, create it
            if 'max_p_mw' not in net.load.columns and 'p_mw' in net.load.columns:
                net.load['max_p_mw'] = net.load['p_mw']
                self.logger.info("Created 'max_p_mw' from 'p_mw' in load table")

            # Ensure max_p_mw exists (set to 0 if neither p_mw nor max_p_mw exist)
            if 'max_p_mw' not in net.load.columns:
                net.load['max_p_mw'] = 0.0
                self.logger.warning("No power data found in loads, set max_p_mw to 0")

            # Also ensure name column exists
            if 'name' not in net.load.columns:
                net.load['name'] = [f"Load_{i}" for i in net.load.index]

    def _ensure_bus_names(self, net: pp.pandapowerNet) -> None:
        """
        Ensure buses have names that match expected conventions.

        Naming conventions:
        - LV transformer bus: contains "LVbus"
        - Consumer buses (with loads): contains "Consumer Nodebus"
        - Connection buses (internal): contains "Connection Nodebus"
        """
        # If buses don't have names, create them from indices
        if 'name' not in net.bus.columns or net.bus['name'].isna().any():
            net.bus['name'] = net.bus.apply(
                lambda row: row['name'] if pd.notna(row.get('name')) else f"Bus_{row.name}",
                axis=1
            )

        # Identify LV bus from transformer
        if not net.trafo.empty:
            lv_bus_idx = net.trafo.iloc[0]['lv_bus']
            if 'LVbus' not in str(net.bus.loc[lv_bus_idx, 'name']):
                net.bus.loc[lv_bus_idx, 'name'] = f"LVbus_{lv_bus_idx}"

        # Identify consumer buses (buses with loads)
        if not net.load.empty:
            consumer_bus_indices = net.load['bus'].unique()
            for bus_idx in consumer_bus_indices:
                current_name = net.bus.loc[bus_idx, 'name']
                if 'Consumer Nodebus' not in str(current_name) and 'LVbus' not in str(current_name):
                    net.bus.loc[bus_idx, 'name'] = f"Consumer Nodebus_{bus_idx}"

        # Identify connection buses (internal buses without loads, excluding LV bus)
        lv_bus_idx = net.trafo.iloc[0]['lv_bus'] if not net.trafo.empty else None
        consumer_bus_indices = set(net.load['bus'].unique()) if not net.load.empty else set()

        for bus_idx in net.bus.index:
            if (bus_idx != lv_bus_idx and
                bus_idx not in consumer_bus_indices and
                'LVbus' not in str(net.bus.loc[bus_idx, 'name']) and
                'Consumer Nodebus' not in str(net.bus.loc[bus_idx, 'name'])):
                net.bus.loc[bus_idx, 'name'] = f"Connection Nodebus_{bus_idx}"

    def _ensure_bus_zones(self, net: pp.pandapowerNet) -> None:
        """
        Ensure buses have zone information.

        Zones are used for simultaneity factor calculations:
        - 'Residential': residential buildings (SFH, MFH, AB, TH)
        - 'Commercial': commercial buildings
        - 'Public': public buildings
        """
        default_zone = self.config.get('default_zone', 'Residential')
        zone_mapping = self.config.get('zone_mapping', {})

        # Add zone column if it doesn't exist
        if 'zone' not in net.bus.columns:
            net.bus['zone'] = default_zone

        # Fill missing zones with default (avoid pandas FutureWarning)
        net.bus['zone'] = net.bus['zone'].fillna(default_zone)

        # Apply zone mapping if provided
        if zone_mapping:
            net.bus['zone'] = net.bus['zone'].replace(zone_mapping)

        # Propagate zones from loads to buses if load zones exist
        if 'zone' in net.load.columns:
            for bus_idx in net.load['bus'].unique():
                load_zones = net.load[net.load['bus'] == bus_idx]['zone'].mode()
                if len(load_zones) > 0:
                    net.bus.loc[bus_idx, 'zone'] = load_zones.iloc[0]

        # Ensure all zones are valid (Residential, Commercial, or Public)
        # Replace any non-standard zones with default
        valid_zones = ['Residential', 'Commercial', 'Public']
        net.bus['zone'] = net.bus['zone'].apply(
            lambda z: z if z in valid_zones else default_zone
        )

    def _ensure_load_zones(self, net: pp.pandapowerNet) -> None:
        """
        Ensure loads have zone information.

        NOTE: The topology_analysis code expects zone to come from the bus table,
        not the load table. If both have 'zone', the merge creates zone_x and zone_y
        which breaks the groupby operations. So we only add zone to loads if it
        doesn't already exist in the bus table.
        """
        # Only add zone to loads if buses don't have zone (unusual case)
        if 'zone' not in net.bus.columns:
            default_zone = self.config.get('default_zone', 'Residential')
            if 'zone' not in net.load.columns:
                net.load['zone'] = default_zone
            else:
                # Normalize existing load zones
                net.load['zone'] = net.load['zone'].fillna(default_zone)
        else:
            # Buses have zones, so remove zone from loads if it exists
            # The merge in calculate_line_with_sim_factor will add it from bus table
            if 'zone' in net.load.columns:
                net.load.drop('zone', axis=1, inplace=True)

    def _validate_network(self, net: pp.pandapowerNet) -> None:
        """
        Validate that the adapted network has required structure.

        Raises
        ------
        ValueError
            If required elements are missing
        """
        # Check for transformer
        if net.trafo.empty:
            raise ValueError("Network must have at least one transformer")

        # Check for LV bus
        lv_buses = net.bus[net.bus['name'].str.contains('LVbus', na=False)]
        if lv_buses.empty:
            raise ValueError("Network must have an LV bus")

        # Warn if no loads
        if net.load.empty:
            self.logger.warning("Network has no loads")

        # Warn if no consumer buses
        consumer_buses = net.bus[net.bus['name'].str.contains('Consumer Nodebus', na=False)]
        if consumer_buses.empty:
            self.logger.warning("Network has no consumer buses")

        self.logger.info(f"Network validated: {len(net.bus)} buses, {len(net.load)} loads, "
                        f"{len(net.line)} lines, {len(net.trafo)} transformers")


def adapt_dso_network(
    net: pp.pandapowerNet,
    lv_bus_keywords: Optional[list] = None,
    consumer_keywords: Optional[list] = None,
    zone_mapping: Optional[Dict[str, str]] = None,
    default_zone: str = 'Residential'
) -> pp.pandapowerNet:
    """
    Convenience function to adapt a DSO network for topology analysis.

    Parameters
    ----------
    net : pp.pandapowerNet
        The pandapower network to adapt
    lv_bus_keywords : list, optional
        Keywords that might identify LV buses in original data
    consumer_keywords : list, optional
        Keywords that might identify consumer buses in original data
    zone_mapping : dict, optional
        Mapping from DSO zone names to standard zones
        Example: {'residential': 'Residential', 'industrial': 'Commercial'}
    default_zone : str
        Default zone for buses/loads without zone information

    Returns
    -------
    pp.pandapowerNet
        Adapted network ready for topology analysis

    Examples
    --------
    >>> net = pp.from_json('dso_network.json')
    >>> adapted_net = adapt_dso_network(
    ...     net,
    ...     zone_mapping={'residential': 'Residential', 'industrial': 'Commercial'}
    ... )
    >>> from src.analysis.standalone_calculator import StandaloneParameterCalculator
    >>> calc = StandaloneParameterCalculator()
    >>> params = calc.compute_parameters(adapted_net)
    """
    config = {
        'lv_bus_pattern': lv_bus_keywords,
        'consumer_bus_pattern': consumer_keywords,
        'zone_mapping': zone_mapping or {},
        'default_zone': default_zone
    }

    adapter = PandapowerNetworkAdapter(net, config)
    return adapter.adapt()

