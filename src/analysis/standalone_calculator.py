"""
Standalone parameter calculator for external networks.

This module provides a database-independent version of the ParameterCalculator
for analyzing external pandapower networks without database dependencies.
"""

import pandas as pd
import pandapower as pp
from typing import Dict, Any, Optional
import logging

# Import only the compute logic, not database dependencies
from src.config_loader import (
    SIM_FACTOR,
    CLUSTERING_PARAMETERS
)


class StandaloneParameterCalculator:
    """
    Database-independent parameter calculator for pandapower networks.

    This class wraps the topology analysis logic without requiring database access,
    making it suitable for analyzing external networks (e.g., from DSO).

    Parameters
    ----------
    lvbus_keyword : str
        Substring to identify the LV root bus in bus names
    consumer_bus_keyword : str
        Substring to identify consumer buses in bus names
    connection_bus_keyword : str
        Substring to identify connection buses in bus names
    """

    def __init__(
        self,
        lvbus_keyword: str = "LVbus",
        consumer_bus_keyword: str = "Consumer Nodebus",
        connection_bus_keyword: str = "Connection Nodebus"
    ):
        self.lvbus_keyword = lvbus_keyword
        self.consumer_bus_keyword = consumer_bus_keyword
        self.connection_bus_keyword = connection_bus_keyword
        self.logger = logging.getLogger(__name__)

        # Import the actual ParameterCalculator to reuse its methods
        # We'll use it as a delegate for computation methods
        from src.analysis.topology_analysis import ParameterCalculator

        # Create a minimal instance just for method access (won't use database methods)
        # Pass dummy values for plz, bcid, kcid since we won't use database
        self._calculator = ParameterCalculator(
            plz=0,
            bcid=0,
            kcid=0,
            keyword_lvbus=lvbus_keyword,
            keyword_consumer_bus=consumer_bus_keyword,
            keyword_connection_bus=connection_bus_keyword
        )

    def compute_parameters(self, net: pp.pandapowerNet) -> Dict[str, Any]:
        """
        Compute topology parameters for a pandapower network.

        This method reuses the existing compute_parameters logic but returns
        only the computed parameters without database interaction.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to analyze

        Returns
        -------
        dict
            Dictionary of computed parameters with keys matching CLUSTERING_PARAMETERS

        Notes
        -----
        The simultaneous_peak_load_mw parameter will be 0.0 since it requires
        database lookup. All other parameters are computed from the network structure.
        """
        try:
            # Call the existing compute_parameters method
            # Note: get_simultaneous_peak_load will fail without database,
            # so we catch and handle it
            params = self._calculator.compute_parameters(net)
            return params
        except (IndexError, KeyError, AttributeError) as e:
            # Database access failed - recompute without simultaneous load lookup
            self.logger.warning(f"Database access failed (expected for standalone mode): {e}")
            self.logger.info("Computing parameters without database-dependent values...")
            return self._compute_parameters_standalone(net)
        except Exception as e:
            self.logger.error(f"Error computing parameters: {e}")
            raise

    def _compute_parameters_standalone(self, net: pp.pandapowerNet) -> Dict[str, Any]:
        """
        Compute parameters without database dependencies.

        This method manually calls the individual calculation methods to avoid
        the database lookup for simultaneous peak load.
        """
        import pandapower.topology as top

        # Use the calculator's individual methods
        calc = self._calculator

        no_house_connections = calc.get_no_of_buses(net, self.consumer_bus_keyword)
        no_connection_buses = calc.get_no_of_buses(net, self.connection_bus_keyword)
        no_households = calc.get_no_households(net)
        max_power_mw = calc.get_max_power(net)

        from src.config_loader import PEAK_LOAD_HOUSEHOLD
        no_household_equ = max_power_mw * 1000.0 / PEAK_LOAD_HOUSEHOLD
        cable_length_km = calc.get_cable_length(net)
        cable_len_per_house = cable_length_km / no_house_connections if no_house_connections > 0 else 0.0

        G = top.create_nxgraph(net, respect_switches=False)
        no_branches = calc.get_no_branches(G, net)
        avg_trafo_dis, max_trafo_dis = calc.get_distances_in_graph(net, G)

        # Zero-division protection for branch metrics
        if no_branches > 0:
            no_house_connections_per_branch = no_house_connections / no_branches
            no_households_per_branch = max_power_mw * 1000.0 / (PEAK_LOAD_HOUSEHOLD * no_branches)
        else:
            no_house_connections_per_branch = 0.0
            no_households_per_branch = 0.0

        transformer_mva = calc.get_trafo_power(net)
        house_distance_km = calc.calc_avg_house_distance(net)

        # Skip database lookup - will estimate later if needed
        simultaneous_peak_load_mw = 0.0

        # Try to calculate resistance - may fail for non-radial networks
        try:
            (max_no_of_households_of_a_branch, resistance, reactance, ratio,
             max_vsw_of_a_branch) = calc.calc_resistance(net, G)
            vsw_per_branch = resistance / no_branches if no_branches > 0 else 0.0
        except (ValueError, KeyError, IndexError) as e:
            self.logger.warning(f"calc_resistance failed (non-radial topology?): {e}")
            # Use fallback values
            max_no_of_households_of_a_branch = 0.0
            resistance = 0.0
            reactance = 0.0
            ratio = 0.0
            max_vsw_of_a_branch = 0.0
            vsw_per_branch = 0.0

        return {
            "no_connection_buses": int(no_connection_buses),
            "no_branches": int(no_branches),
            "no_house_connections": int(no_house_connections),
            "no_house_connections_per_branch": float(no_house_connections_per_branch),
            "no_households": int(no_households),
            "no_household_equ": float(no_household_equ),
            "no_households_per_branch": float(no_households_per_branch),
            "max_no_of_households_of_a_branch": float(max_no_of_households_of_a_branch),
            "house_distance_km": float(house_distance_km),
            "transformer_mva": float(transformer_mva),
            "max_trafo_dis": float(max_trafo_dis),
            "avg_trafo_dis": float(avg_trafo_dis),
            "cable_length_km": float(cable_length_km),
            "cable_len_per_house": float(cable_len_per_house),
            "max_power_mw": float(max_power_mw),
            "simultaneous_peak_load_mw": float(simultaneous_peak_load_mw),
            "resistance": float(resistance),
            "reactance": float(reactance),
            "ratio": float(ratio),
            "vsw_per_branch": float(vsw_per_branch),
            "max_vsw_of_a_branch": float(max_vsw_of_a_branch)
        }

    def compute_parameters_with_fallback(
        self,
        net: pp.pandapowerNet,
        estimate_simultaneous_load: bool = True
    ) -> Dict[str, Any]:
        """
        Compute parameters with fallback estimation for database-dependent values.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to analyze
        estimate_simultaneous_load : bool
            If True, estimate simultaneous peak load using simple heuristics
            instead of database lookup

        Returns
        -------
        dict
            Dictionary of computed parameters
        """
        # Compute standard parameters
        params = self.compute_parameters(net)

        # If simultaneous load is 0 and estimation is requested, estimate it
        if estimate_simultaneous_load and params['simultaneous_peak_load_mw'] == 0.0:
            params['simultaneous_peak_load_mw'] = self._estimate_simultaneous_peak_load(net)

        return params

    def _estimate_simultaneous_peak_load(self, net: pp.pandapowerNet) -> float:
        """
        Estimate simultaneous peak load using category-based simultaneity factors.

        This is a simple estimation that doesn't account for distance-based
        variations but provides a reasonable approximation.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network

        Returns
        -------
        float
            Estimated simultaneous peak load in MW
        """
        from src import utils

        total_sim_load = 0.0

        # Process loads by zone (Residential, Commercial, Public)
        for zone in ['Residential', 'Commercial', 'Public']:
            # Get buses of this zone
            zone_bus_indices = []
            if 'zone' in net.bus.columns:
                zone_buses = net.bus[net.bus['zone'] == zone].index.tolist()
                zone_bus_indices.extend(zone_buses)

            # Also check load zones
            if 'zone' in net.load.columns:
                zone_loads = net.load[net.load['zone'] == zone]
                zone_bus_indices.extend(zone_loads['bus'].tolist())

            zone_bus_indices = list(set(zone_bus_indices))

            if not zone_bus_indices:
                continue

            # Get loads on these buses
            zone_load_df = net.load[net.load['bus'].isin(zone_bus_indices)]

            if zone_load_df.empty:
                continue

            # Calculate total installed power and count
            total_power_mw = zone_load_df['max_p_mw'].sum()
            load_count = len(zone_load_df)

            if load_count > 0:
                # Apply simultaneity factor
                sim_factor = SIM_FACTOR.get(zone, 0.2)
                sim_load = utils.oneSimultaneousLoad(
                    installed_power=total_power_mw,
                    load_count=load_count,
                    sim_factor=sim_factor
                )
                total_sim_load += sim_load

        return total_sim_load

    def get_parameters_as_dataframe(self, net: pp.pandapowerNet) -> pd.DataFrame:
        """
        Return parameters as a one-row DataFrame.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to analyze

        Returns
        -------
        pd.DataFrame
            One-row DataFrame with parameter columns
        """
        params = self.compute_parameters_with_fallback(net)
        return pd.DataFrame([params], columns=CLUSTERING_PARAMETERS)

    def analyze_and_export(
        self,
        net: pp.pandapowerNet,
        output_path: Optional[str] = None,
        output_format: str = 'json'
    ) -> Dict[str, Any]:
        """
        Analyze a network and optionally export results.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to analyze
        output_path : str, optional
            Path to save results. If None, results are only returned.
        output_format : str
            Output format: 'json', 'csv', or 'excel'

        Returns
        -------
        dict
            Dictionary of computed parameters
        """
        import json

        params = self.compute_parameters_with_fallback(net)

        if output_path:
            if output_format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(params, f, indent=2)
                self.logger.info(f"Results saved to {output_path}")

            elif output_format == 'csv':
                df = pd.DataFrame([params])
                df.to_csv(output_path, index=False)
                self.logger.info(f"Results saved to {output_path}")

            elif output_format == 'excel':
                df = pd.DataFrame([params])
                df.to_excel(output_path, index=False)
                self.logger.info(f"Results saved to {output_path}")

            else:
                raise ValueError(f"Unsupported output format: {output_format}")

        return params


def analyze_dso_network(
    net_path: str,
    output_path: Optional[str] = None,
    adapt_network: bool = True,
    zone_mapping: Optional[Dict[str, str]] = None,
    **adapter_kwargs
) -> Dict[str, Any]:
    """
    Convenience function to analyze a DSO network from file.

    Parameters
    ----------
    net_path : str
        Path to pandapower JSON file
    output_path : str, optional
        Path to save analysis results
    adapt_network : bool
        Whether to adapt the network structure (recommended for DSO data)
    zone_mapping : dict, optional
        Mapping from DSO zone names to standard zones
    **adapter_kwargs
        Additional arguments passed to the network adapter

    Returns
    -------
    dict
        Dictionary of computed parameters

    Examples
    --------
    >>> results = analyze_dso_network(
    ...     '/data/SWF_V7.json',
    ...     output_path='/data/SWF_V7_analysis.json',
    ...     zone_mapping={'residential': 'Residential'}
    ... )
    >>> print(f"Cable length: {results['cable_length_km']:.2f} km")
    """
    # Load network
    net = pp.from_json(net_path)

    # Adapt if requested
    if adapt_network:
        from src.analysis.data_adapter import adapt_dso_network as adapt_net
        net = adapt_net(net, zone_mapping=zone_mapping, **adapter_kwargs)

    # Analyze
    calculator = StandaloneParameterCalculator()
    results = calculator.analyze_and_export(
        net,
        output_path=output_path,
        output_format='json' if output_path and output_path.endswith('.json') else 'csv'
    )

    return results

