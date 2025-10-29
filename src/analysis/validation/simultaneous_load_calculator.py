"""
Simultaneous load calculator for external networks without database dependencies.

This module provides methods to calculate simultaneous peak load by:
1. Aggregating loads by zone (Residential, Commercial, Public)
2. Applying zone-specific simultaneity factors
3. Optionally calculating per-line simultaneous loads for detailed analysis

Based on the approach from the original grid generation code but simplified
and adapted for validation/external network analysis.
"""

import pandas as pd
import pandapower as pp
import networkx as nx
from typing import Dict, Tuple, Optional
import logging

from src.config_loader import SIM_FACTOR, PEAK_LOAD_HOUSEHOLD
from src.utils import oneSimultaneousLoad


class SimultaneousLoadCalculator:
    """
    Calculate simultaneous peak loads for networks without database access.

    This calculator uses zone-based simultaneity factors and can optionally
    compute per-line simultaneous loads for detailed network analysis.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.sim_factors = SIM_FACTOR  # {'Residential': 0.2, 'Commercial': 0.6, 'Public': 0.9}

    def calculate_total_simultaneous_load(
        self,
        net: pp.pandapowerNet,
        method: str = 'zone_based'
    ) -> float:
        """
        Calculate total simultaneous peak load for the entire network.

        Parameters
        ----------
        net : pp.pandapowerNet
            Network to analyze
        method : str
            Calculation method:
            - 'zone_based': Simple aggregation by load zones (fast, recommended)
            - 'topology_based': Per-line calculation considering network topology (detailed)

        Returns
        -------
        float
            Total simultaneous peak load in MW
        """
        if method == 'zone_based':
            return self._calculate_zone_based(net)
        elif method == 'topology_based':
            return self._calculate_topology_based(net)
        else:
            raise ValueError(f"Unknown method: {method}. Use 'zone_based' or 'topology_based'")

    def _calculate_zone_based(self, net: pp.pandapowerNet) -> float:
        """
        Calculate simultaneous load by aggregating loads per zone.

        This is the recommended method for validation/comparison as it's:
        - Simple and fast
        - Doesn't depend on radial topology assumptions
        - Works with meshed networks

        Returns
        -------
        float
            Total simultaneous peak load in MW
        """
        if net.load.empty:
            return 0.0

        # Ensure we have zone information - get it from buses if not in loads
        loads_with_zones = self._get_loads_with_zones(net)

        if loads_with_zones.empty:
            self.logger.warning("No loads with zone information found, using default Residential zone")
            loads_with_zones = net.load.copy()
            loads_with_zones['zone'] = 'Residential'

        total_sim_load = 0.0

        # Process each zone separately
        for zone in ['Residential', 'Commercial', 'Public']:
            zone_loads = loads_with_zones[loads_with_zones['zone'] == zone]

            if zone_loads.empty:
                continue

            # Sum installed power for this zone
            total_power = zone_loads['max_p_mw'].sum()
            load_count = len(zone_loads)

            # Apply simultaneity factor
            sim_factor = self.sim_factors.get(zone, 0.2)
            sim_load = oneSimultaneousLoad(
                installed_power=total_power,
                load_count=load_count,
                sim_factor=sim_factor
            )

            total_sim_load += sim_load

            self.logger.debug(f"Zone {zone}: {load_count} loads, "
                            f"{total_power:.3f} MW installed, "
                            f"{sim_load:.3f} MW simultaneous (factor: {sim_factor})")

        self.logger.info(f"Total simultaneous peak load: {total_sim_load:.3f} MW")
        return total_sim_load

    def _calculate_topology_based(self, net: pp.pandapowerNet) -> Tuple[float, pd.DataFrame]:
        """
        Calculate simultaneous load considering network topology.

        This method walks the network tree from leaves to root, aggregating
        loads and applying simultaneity factors at each junction. More accurate
        for radial networks but may fail on meshed topologies.

        Returns
        -------
        tuple
            (total_simultaneous_load_mw, line_dataframe_with_sim_factors)
        """
        if net.load.empty:
            return 0.0, pd.DataFrame()

        if net.trafo.empty:
            self.logger.warning("No transformer found, cannot perform topology-based calculation")
            return self._calculate_zone_based(net), pd.DataFrame()

        try:
            # Create network graph
            import pandapower.topology as top
            # CRITICAL FIX: respect_switches=True for operational topology
            G = top.create_nxgraph(net, respect_switches=True)

            # Get root bus (LV side of transformer)
            root_bus = net.trafo['lv_bus'].iloc[0]

            # Calculate per-line simultaneous loads
            line_df = self._annotate_lines_with_sim_loads(net, G, root_bus)

            # Total simultaneous load is at the transformer connection
            trafo_line = line_df[line_df['name'] == 'trafo']
            if not trafo_line.empty:
                total_sim_load = trafo_line['sim_load'].iloc[0]
            else:
                # Fallback to zone-based if topology calculation failed
                self.logger.warning("Topology-based calculation incomplete, falling back to zone-based")
                total_sim_load = self._calculate_zone_based(net)

            return total_sim_load, line_df

        except Exception as e:
            self.logger.warning(f"Topology-based calculation failed: {e}. Using zone-based method.")
            return self._calculate_zone_based(net), pd.DataFrame()

    def _get_loads_with_zones(self, net: pp.pandapowerNet) -> pd.DataFrame:
        """
        Get loads with zone information from buses.

        Zone should be in bus table, not load table (as per network adapter).
        """
        # Merge loads with bus zone information
        loads = net.load.copy()
        buses = net.bus[['zone']].copy() if 'zone' in net.bus.columns else pd.DataFrame()

        if buses.empty:
            return pd.DataFrame()

        loads_with_zones = loads.merge(buses, left_on='bus', right_index=True, how='left')

        # Fill missing zones with Residential (conservative assumption)
        if 'zone' in loads_with_zones.columns:
            loads_with_zones['zone'] = loads_with_zones['zone'].fillna('Residential')
        else:
            loads_with_zones['zone'] = 'Residential'

        return loads_with_zones

    def _annotate_lines_with_sim_loads(
        self,
        net: pp.pandapowerNet,
        G: nx.Graph,
        root_bus: int
    ) -> pd.DataFrame:
        """
        Annotate each line with simultaneous load considering downstream loads.

        This is a simplified version of the original calculate_line_with_sim_factor
        that's more maintainable.

        Parameters
        ----------
        net : pp.pandapowerNet
            Network to analyze
        G : networkx.Graph
            Network graph
        root_bus : int
            Root bus (transformer LV side)

        Returns
        -------
        pd.DataFrame
            Lines dataframe with simultaneous load annotations
        """
        # Initialize line dataframe with sim load columns
        lines = net.line.copy()

        # Ensure lines point from root to leaves
        lines = self._orient_lines_from_root(lines, net.trafo['lv_bus'].iloc[0])

        # Initialize columns
        for col in ['sim_load', 'no_residential', 'load_residential_mw',
                    'no_commercial', 'load_commercial_mw',
                    'no_public', 'load_public_mw', 'sim_factor_cumulated']:
            lines[col] = 0.0

        # Get loads with zones
        loads_with_zones = self._get_loads_with_zones(net)

        # Step 1: Annotate lines directly connected to loads
        self._annotate_consumer_lines(lines, loads_with_zones)

        # Step 2: Aggregate up the tree from leaves to root
        self._aggregate_loads_to_root(lines, net, G, root_bus)

        # Step 3: Add virtual transformer line for total
        trafo_line = self._create_transformer_line(lines, net, root_bus)
        lines = pd.concat([lines, trafo_line], ignore_index=True)

        return lines

    def _orient_lines_from_root(self, lines: pd.DataFrame, root_bus: int) -> pd.DataFrame:
        """Ensure all lines point from root (transformer) towards leaves (loads)."""
        # Reverse lines that point towards the transformer
        mask = lines['to_bus'] == root_bus
        lines.loc[mask, ['from_bus', 'to_bus']] = lines.loc[mask, ['to_bus', 'from_bus']].values
        return lines

    def _annotate_consumer_lines(self, lines: pd.DataFrame, loads_with_zones: pd.DataFrame):
        """Annotate lines directly connected to load buses with sim factors."""
        # Group loads by bus and zone
        for bus in loads_with_zones['bus'].unique():
            bus_loads = loads_with_zones[loads_with_zones['bus'] == bus]

            # Find line(s) connected to this bus
            line_indices = lines[lines['to_bus'] == bus].index

            if len(line_indices) == 0:
                continue

            line_idx = line_indices[0]  # Take first if multiple

            # Aggregate by zone
            for zone in ['Residential', 'Commercial', 'Public']:
                zone_loads = bus_loads[bus_loads['zone'] == zone]
                if zone_loads.empty:
                    continue

                count = len(zone_loads)
                total_power = zone_loads['max_p_mw'].sum()

                # Calculate simultaneous load for this zone
                sim_factor = self.sim_factors.get(zone, 0.2)
                sim_load = oneSimultaneousLoad(
                    installed_power=total_power,
                    load_count=count,
                    sim_factor=sim_factor
                )

                # Store in line dataframe
                zone_lower = zone.lower()
                lines.at[line_idx, f'no_{zone_lower}'] = count
                lines.at[line_idx, f'load_{zone_lower}_mw'] = total_power
                lines.at[line_idx, 'sim_load'] += sim_load

            # Calculate overall simultaneity factor for this line
            total_installed = (lines.at[line_idx, 'load_residential_mw'] +
                             lines.at[line_idx, 'load_commercial_mw'] +
                             lines.at[line_idx, 'load_public_mw'])

            if total_installed > 0:
                lines.at[line_idx, 'sim_factor_cumulated'] = (
                    lines.at[line_idx, 'sim_load'] / total_installed
                )

    def _aggregate_loads_to_root(
        self,
        lines: pd.DataFrame,
        net: pp.pandapowerNet,
        G: nx.Graph,
        root_bus: int
    ):
        """Aggregate loads from leaves to root along network topology."""
        # Get all buses sorted by distance from root (furthest first)
        buses_by_distance = []
        for bus in net.bus.index:
            if bus == root_bus:
                continue
            try:
                distance = nx.shortest_path_length(G, source=root_bus, target=bus)
                buses_by_distance.append((bus, distance))
            except nx.NetworkXNoPath:
                continue

        # Sort by distance descending (process furthest first)
        buses_by_distance.sort(key=lambda x: x[1], reverse=True)

        # Aggregate loads
        for bus, _ in buses_by_distance:
            # Find downstream lines (emanating from this bus)
            downstream_lines = lines[lines['from_bus'] == bus]

            # Find upstream line (pointing to this bus)
            upstream_lines = lines[lines['to_bus'] == bus]

            if upstream_lines.empty:
                continue  # No upstream connection

            upstream_idx = upstream_lines.index[0]

            # Sum all downstream loads
            for zone in ['residential', 'commercial', 'public']:
                lines.at[upstream_idx, f'no_{zone}'] = downstream_lines[f'no_{zone}'].sum()
                lines.at[upstream_idx, f'load_{zone}_mw'] = downstream_lines[f'load_{zone}_mw'].sum()

            # Calculate simultaneous load for aggregated loads
            for zone in ['Residential', 'Commercial', 'Public']:
                zone_lower = zone.lower()
                total_power = lines.at[upstream_idx, f'load_{zone_lower}_mw']
                count = lines.at[upstream_idx, f'no_{zone_lower}']

                if count > 0:
                    sim_factor = self.sim_factors.get(zone, 0.2)
                    sim_load = oneSimultaneousLoad(
                        installed_power=total_power,
                        load_count=int(count),
                        sim_factor=sim_factor
                    )
                    lines.at[upstream_idx, 'sim_load'] += sim_load

            # Calculate simultaneity factor
            total_installed = (lines.at[upstream_idx, 'load_residential_mw'] +
                             lines.at[upstream_idx, 'load_commercial_mw'] +
                             lines.at[upstream_idx, 'load_public_mw'])

            if total_installed > 0:
                lines.at[upstream_idx, 'sim_factor_cumulated'] = (
                    lines.at[upstream_idx, 'sim_load'] / total_installed
                )

    def _create_transformer_line(
        self,
        lines: pd.DataFrame,
        net: pp.pandapowerNet,
        root_bus: int
    ) -> pd.DataFrame:
        """Create virtual transformer line with total simultaneous load."""
        # Aggregate all lines emanating from root
        root_lines = lines[lines['from_bus'] == root_bus]

        trafo_data = {
            'name': 'trafo',
            'std_type': 'virtual_trafo_line',
            'from_bus': net.trafo['hv_bus'].iloc[0],
            'to_bus': root_bus,
            'no_residential': root_lines['no_residential'].sum(),
            'load_residential_mw': root_lines['load_residential_mw'].sum(),
            'no_commercial': root_lines['no_commercial'].sum(),
            'load_commercial_mw': root_lines['load_commercial_mw'].sum(),
            'no_public': root_lines['no_public'].sum(),
            'load_public_mw': root_lines['load_public_mw'].sum(),
        }

        # Calculate total simultaneous load
        total_sim_load = 0.0
        for zone in ['Residential', 'Commercial', 'Public']:
            zone_lower = zone.lower()
            total_power = trafo_data[f'load_{zone_lower}_mw']
            count = trafo_data[f'no_{zone_lower}']

            if count > 0:
                sim_factor = self.sim_factors.get(zone, 0.2)
                sim_load = oneSimultaneousLoad(
                    installed_power=total_power,
                    load_count=int(count),
                    sim_factor=sim_factor
                )
                total_sim_load += sim_load

        trafo_data['sim_load'] = total_sim_load

        # Calculate overall simultaneity factor
        total_installed = (trafo_data['load_residential_mw'] +
                         trafo_data['load_commercial_mw'] +
                         trafo_data['load_public_mw'])

        if total_installed > 0:
            trafo_data['sim_factor_cumulated'] = total_sim_load / total_installed
        else:
            trafo_data['sim_factor_cumulated'] = 0.0

        return pd.DataFrame([trafo_data])

    def get_breakdown_by_zone(self, net: pp.pandapowerNet) -> Dict[str, Dict[str, float]]:
        """
        Get detailed breakdown of simultaneous load by zone.

        Returns
        -------
        dict
            Dictionary with structure:
            {
                'Residential': {
                    'count': int,
                    'installed_mw': float,
                    'simultaneous_mw': float,
                    'sim_factor': float
                },
                ...
            }
        """
        loads_with_zones = self._get_loads_with_zones(net)

        if loads_with_zones.empty:
            return {}

        breakdown = {}

        for zone in ['Residential', 'Commercial', 'Public']:
            zone_loads = loads_with_zones[loads_with_zones['zone'] == zone]

            if zone_loads.empty:
                continue

            count = len(zone_loads)
            installed_mw = zone_loads['max_p_mw'].sum()
            sim_factor = self.sim_factors.get(zone, 0.2)
            simultaneous_mw = oneSimultaneousLoad(
                installed_power=installed_mw,
                load_count=count,
                sim_factor=sim_factor
            )

            breakdown[zone] = {
                'count': count,
                'installed_mw': installed_mw,
                'simultaneous_mw': simultaneous_mw,
                'sim_factor': sim_factor,
                'effective_factor': simultaneous_mw / installed_mw if installed_mw > 0 else 0.0
            }

        return breakdown


# Convenience function
def calculate_simultaneous_peak_load(
    net: pp.pandapowerNet,
    method: str = 'zone_based',
    return_breakdown: bool = False
) -> float:
    """
    Calculate simultaneous peak load for a network.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network to analyze
    method : str
        'zone_based' (recommended) or 'topology_based'
    return_breakdown : bool
        If True, also return zone breakdown dictionary

    Returns
    -------
    float or tuple
        Simultaneous peak load in MW, optionally with breakdown dict

    Examples
    --------
    """
    calc = SimultaneousLoadCalculator()
    sim_load = calc.calculate_total_simultaneous_load(net, method=method)

    if return_breakdown:
        breakdown = calc.get_breakdown_by_zone(net)
        return sim_load, breakdown

    return sim_load

# Alias for compatibility with metrics_calculator
def estimate_simultaneous_load(net, method='zone_based'):
    """
    Estimate simultaneous peak load for a network.
    Parameters
    ----------
    net : pp.pandapowerNet
        Network to analyze
    method : str
        'zone_based' (recommended) or 'topology_based'
    Returns
    -------
    float
        Simultaneous peak load in MW
    """
    return calculate_simultaneous_peak_load(net, method=method)
