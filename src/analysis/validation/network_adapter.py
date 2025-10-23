"""
Unified network adapter for external pandapower networks.

This module provides a single adapter that works with different network formats:
- SWD networks (with hierarchical chr_name convention)
- Forchheim networks (with continuous numeric chr_name)
- Generic networks (any other format)

The adapter normalizes external networks to match the structure expected by
topology analysis functions, without requiring database access.
"""

import pandas as pd
import pandapower as pp
from typing import Optional, Dict, Any
import logging
import copy

from ..utils import (
    ensure_numeric_types,
    normalize_load_columns,
    normalize_bus_names,
    validate_network_structure
)
from .naming_conventions import (
    detect_naming_convention,
    enhance_network_with_swd_info,
    identify_bus_types_in_network
)


class NetworkAdapter:
    """
    Universal adapter to normalize external pandapower networks for topology analysis.

    This adapter ensures that external networks (e.g., from DSO) have the required
    structure (bus naming conventions, zones, etc.) for compatibility with the
    ParameterCalculator without modifying the original analysis code.

    Supports automatic detection of naming conventions (SWD, Forchheim, generic).
    """

    def __init__(
        self,
        net: pp.pandapowerNet,
        naming_convention: str = 'auto',
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the adapter with a pandapower network.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to adapt
        naming_convention : str
            One of: 'auto', 'swd', 'forchheim', 'generic'
            If 'auto', will attempt to detect the convention
        config : dict, optional
            Configuration for adaptation. Keys:
            - 'default_zone': Default zone for loads without zone info (default: 'Residential')
            - 'zone_mapping': Dict to map existing zones to standard zones
            - 'skip_validation': Skip structure validation (default: False)
        """
        self.original_net = net
        self.naming_convention = naming_convention
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
        self.logger.info("Starting network adaptation...")

        # Create a deep copy to avoid modifying the original
        adapted_net = copy.deepcopy(self.original_net)

        # Detect naming convention if auto
        if self.naming_convention == 'auto':
            self.naming_convention = detect_naming_convention(adapted_net)
            self.logger.info(f"Detected naming convention: {self.naming_convention}")

        # Apply adaptations in sequence
        self._ensure_numeric_types(adapted_net)
        self._enhance_with_naming_metadata(adapted_net)
        self._normalize_structure(adapted_net)
        self._ensure_bus_zones(adapted_net)
        self._ensure_load_zones(adapted_net)

        # Validate if not skipped
        if not self.config.get('skip_validation', False):
            self._validate_network(adapted_net)

        self.logger.info(f"Network adaptation complete: {len(adapted_net.bus)} buses, "
                        f"{len(adapted_net.load)} loads, {len(adapted_net.line)} lines")

        return adapted_net

    def _ensure_numeric_types(self, net: pp.pandapowerNet) -> None:
        """Ensure all numeric columns are proper types."""
        self.logger.debug("Converting numeric columns to proper types...")
        ensure_numeric_types(net)

    def _enhance_with_naming_metadata(self, net: pp.pandapowerNet) -> None:
        """Parse and add metadata from naming convention."""
        if self.naming_convention == 'swd':
            self.logger.debug("Parsing SWD naming convention...")
            enhance_network_with_swd_info(net)
        elif self.naming_convention == 'forchheim':
            self.logger.debug("Parsing Forchheim naming convention...")
            # Forchheim uses similar structure to SWD
            enhance_network_with_swd_info(net)
        # Generic networks don't have special naming to parse

    def _normalize_structure(self, net: pp.pandapowerNet) -> None:
        """Normalize network structure (buses, loads, names)."""
        self.logger.debug("Normalizing network structure...")

        # Ensure bus names exist
        normalize_bus_names(net)

        # Ensure load columns exist
        normalize_load_columns(net)

        # Identify and standardize bus types
        identify_bus_types_in_network(net, self.naming_convention)

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

        # Fill missing zones with default
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
        valid_zones = ['Residential', 'Commercial', 'Public']
        net.bus['zone'] = net.bus['zone'].apply(
            lambda z: z if z in valid_zones else default_zone
        )

        self.logger.debug(f"Zone distribution: {net.bus['zone'].value_counts().to_dict()}")

    def _ensure_load_zones(self, net: pp.pandapowerNet) -> None:
        """
        Ensure loads have zone information from their connected buses.

        NOTE: The topology_analysis code expects zone to come from the bus table,
        not the load table. If both have 'zone', the merge creates zone_x and zone_y
        which breaks the groupby operations. So we remove zone from loads.
        """
        # Buses should have zones now, so remove zone from loads if it exists
        if 'zone' in net.load.columns:
            net.load.drop('zone', axis=1, inplace=True)
            self.logger.debug("Removed 'zone' from loads (will use bus zones)")

    def _validate_network(self, net: pp.pandapowerNet) -> None:
        """
        Validate that the adapted network has required structure.

        Raises
        ------
        ValueError
            If critical elements are missing
        """
        issues = validate_network_structure(net)

        for issue in issues:
            if "transformer" in issue.lower():
                raise ValueError(issue)
            else:
                self.logger.warning(issue)

        self.logger.info("Network structure validated successfully")


def adapt_network(
    net: pp.pandapowerNet,
    naming_convention: str = 'auto',
    zone_mapping: Optional[Dict[str, str]] = None,
    default_zone: str = 'Residential',
    **kwargs
) -> pp.pandapowerNet:
    """
    Convenience function to adapt an external network for topology analysis.

    Parameters
    ----------
    net : pp.pandapowerNet
        The pandapower network to adapt
    naming_convention : str
        One of: 'auto', 'swd', 'forchheim', 'generic'
    zone_mapping : dict, optional
        Mapping from DSO zone names to standard zones
        Example: {'residential': 'Residential', 'industrial': 'Commercial'}
    default_zone : str
        Default zone for buses/loads without zone information
    **kwargs
        Additional configuration options

    Returns
    -------
    pp.pandapowerNet
        Adapted network ready for topology analysis

    Examples
    --------
    >>> net = pp.from_json('dso_network.json')
    >>> adapted_net = adapt_network(
    ...     net,
    ...     zone_mapping={'residential': 'Residential', 'industrial': 'Commercial'}
    ... )
    >>> from src.analysis.validation.metrics_calculator import MetricsCalculator
    >>> calc = MetricsCalculator()
    >>> metrics = calc.compute_metrics(adapted_net)
    """
    # Build config
    config = {
        'zone_mapping': zone_mapping or {},
        'default_zone': default_zone
    }
    config.update(kwargs)

    # Create adapter and run
    adapter = NetworkAdapter(net, naming_convention=naming_convention, config=config)
    return adapter.adapt()

