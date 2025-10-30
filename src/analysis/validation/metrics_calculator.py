"""
Database-independent metrics calculator for external networks.

This module provides a standalone version of the ParameterCalculator
for analyzing external pandapower networks without database dependencies.
Renamed from StandaloneParameterCalculator to MetricsCalculator for clarity.
"""

import pandas as pd
import pandapower as pp
import networkx as nx
from typing import Dict, Any, Optional, List, Callable, Union
import logging
import json
import re
from pathlib import Path

# Import only the compute logic, not database dependencies
from src.config_loader import (
    SIM_FACTOR,
    CLUSTERING_PARAMETERS,
)


class MetricsCalculator:
    """
    Database-independent metrics calculator for pandapower networks.

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
        from .topology_analysis import ParameterCalculator

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
        # Suppress noisy DB logger in standalone mode
        try:
            self._calculator.dbc.logger.setLevel(logging.ERROR)
        except Exception:
            pass

    def compute_metrics(self, net: pp.pandapowerNet) -> Dict[str, Any]:
        """
        Compute topology metrics for a pandapower network.

        This method reuses the existing compute_parameters logic but returns
        only the computed metrics without database interaction.

        Parameters
        ----------
        net : pp.pandapowerNet
            The pandapower network to analyze

        Returns
        -------
        dict
            Dictionary of computed metrics with keys matching CLUSTERING_PARAMETERS

        Notes
        -----
        The simultaneous_peak_load_mw metric will be 0.0 since it requires
        database lookup. All other metrics are computed from the network structure.
        """
        # Always use the standalone path for external nets to avoid DB and heavy lookups
        return self._compute_metrics_standalone(net)

    def _prepare_external_net_for_metrics(self, net: pp.pandapowerNet) -> pp.pandapowerNet:
        """Patch external/DSO subgrid to match ParameterCalculator expectations.

        - Ensure load.max_p_mw exists (copy from p_mw if needed)
        - Ensure sgen.max_p_mw exists (copy from p_mw if present)
        - Ensure bus.zone exists (default 'Residential')
        - Mark LV root bus name to include lvbus_keyword (trafo.lv_bus)
        - Mark consumer buses (with loads or sgens) to include consumer_bus_keyword in names
        - Mark remaining buses as connection buses by including connection_bus_keyword
        """
        # 1) load.max_p_mw
        if hasattr(net, 'load'):
            if 'max_p_mw' not in net.load.columns:
                if 'p_mw' in net.load.columns:
                    net.load['max_p_mw'] = net.load['p_mw']
                else:
                    net.load['max_p_mw'] = 0.0
            else:
                net.load['max_p_mw'] = net.load['max_p_mw'].fillna(0.0)
        # 1b) sgen.max_p_mw
        if hasattr(net, 'sgen'):
            if 'max_p_mw' not in net.sgen.columns:
                if 'p_mw' in net.sgen.columns:
                    net.sgen['max_p_mw'] = net.sgen['p_mw']
                else:
                    net.sgen['max_p_mw'] = 0.0
            else:
                net.sgen['max_p_mw'] = net.sgen['max_p_mw'].fillna(0.0)
        # 2) bus.zone
        if hasattr(net, 'bus') and len(net.bus) > 0:
            if 'zone' not in net.bus.columns:
                net.bus['zone'] = 'Residential'
            else:
                net.bus['zone'] = net.bus['zone'].fillna('Residential')
        # 3) Names
        try:
            # ensure string names
            if 'name' not in net.bus.columns:
                net.bus['name'] = ''
            net.bus['name'] = net.bus['name'].astype(str).fillna('')
            # LV bus
            lv_bus = None
            if hasattr(net, 'trafo') and len(net.trafo) > 0 and 'lv_bus' in net.trafo.columns:
                lv_bus = int(net.trafo['lv_bus'].iloc[0])
                if lv_bus in net.bus.index:
                    nm = net.bus.at[lv_bus, 'name']
                    if self.lvbus_keyword not in nm:
                        net.bus.at[lv_bus, 'name'] = (nm + ' ' + self.lvbus_keyword).strip()
            # consumer buses
            consumer_buses = []
            if hasattr(net, 'load') and len(net.load) > 0 and 'bus' in net.load.columns:
                consumer_buses.extend(list(set(net.load['bus'].astype(int).tolist())))
            if hasattr(net, 'sgen') and len(net.sgen) > 0 and 'bus' in net.sgen.columns:
                consumer_buses.extend(list(set(net.sgen['bus'].astype(int).tolist())))
            consumer_buses = list(set(consumer_buses))
            for b in consumer_buses:
                if b in net.bus.index:
                    nm = net.bus.at[b, 'name']
                    if self.consumer_bus_keyword not in nm:
                        net.bus.at[b, 'name'] = (nm + ' ' + self.consumer_bus_keyword).strip()
            # connection buses (others)
            for b in net.bus.index.tolist():
                if (lv_bus is not None and b == lv_bus) or (b in consumer_buses):
                    continue
                nm = net.bus.at[b, 'name']
                if self.connection_bus_keyword not in nm:
                    net.bus.at[b, 'name'] = (nm + ' ' + self.connection_bus_keyword).strip()
        except Exception:
            pass
        return net

    def _return_zero_metrics(self) -> Dict[str, Any]:
        """Return a dict of zero/default metrics when analysis fails."""
        return {
            "no_connection_buses": 0,
            "no_branches": 0,
            "no_house_connections": 0,
            "no_house_connections_per_branch": 0.0,
            "no_households": 0,
            "no_household_equ": 0.0,
            "no_households_per_branch": 0.0,
            "max_no_of_households_of_a_branch": 0.0,
            "house_distance_km": 0.0,
            "transformer_mva": 0.0,
            "max_trafo_dis": 0.0,
            "avg_trafo_dis": 0.0,
            "cable_length_km": 0.0,
            "cable_len_per_house": 0.0,
            "max_power_mw": 0.0,
            "simultaneous_peak_load_mw": 0.0,
            "resistance": 0.0,
            "reactance": 0.0,
            "ratio": 0.0,
            "vsw_per_branch": 0.0,
            "max_vsw_of_a_branch": 0.0
        }

    def _compute_metrics_standalone(self, net: pp.pandapowerNet) -> Dict[str, Any]:
        """
        Compute parameters without database dependencies.

        This method manually calls the individual calculation methods to avoid
        the database lookup for simultaneous peak load.

        CRITICAL: Uses respect_switches=True to analyze operational (radial) topology
        instead of physical (potentially meshed) topology. This is essential for
        DSO networks that use open switches to create radial operation.
        """
        import pandapower.topology as top

        # Ensure normalization
        net = self._prepare_external_net_for_metrics(net)
        # Use the calculator's individual methods
        calc = self._calculator

        no_house_connections = calc.get_no_of_buses(net, self.consumer_bus_keyword)
        no_connection_buses = calc.get_no_of_buses(net, self.connection_bus_keyword)
        no_households = calc.get_no_households(net)
        # Total installed power: loads plus sgens (use max_p_mw where present)
        max_power_mw = 0.0
        try:
            max_power_mw += float(getattr(net, 'load').get('max_p_mw', pd.Series()).sum()) if hasattr(net,'load') else 0.0
        except Exception:
            pass
        try:
            max_power_mw += float(getattr(net, 'sgen').get('max_p_mw', pd.Series()).sum()) if hasattr(net,'sgen') else 0.0
        except Exception:
            pass
        from src.config_loader import PEAK_LOAD_HOUSEHOLD
        no_household_equ = max_power_mw * 1000.0 / PEAK_LOAD_HOUSEHOLD
        cable_length_km = calc.get_cable_length(net)
        cable_len_per_house = cable_length_km / no_house_connections if no_house_connections > 0 else 0.0

        # CRITICAL FIX: respect_switches=True to get operational radial topology
        try:
            G = top.create_nxgraph(net, respect_switches=True)
        except Exception as e:
            self.logger.warning(f"Failed to create graph with respect_switches: {e}, trying without")
            try:
                G = top.create_nxgraph(net, respect_switches=False)
            except Exception as e2:
                self.logger.error(f"Failed to create graph entirely: {e2}")
                # Return zeros for all metrics
                return self._return_zero_metrics()

        # CRITICAL: Handle multi-component graphs (due to in_service=False lines)
        # Only analyze the largest connected component containing the transformer LV bus
        if nx.number_connected_components(G) > 1:
            self.logger.debug(f"Multi-component graph detected ({nx.number_connected_components(G)} components)")
            # Find transformer LV bus
            if len(net.trafo) > 0 and 'lv_bus' in net.trafo.columns:
                lv_bus = int(net.trafo['lv_bus'].iloc[0])
                if lv_bus in G:
                    # Get component containing LV bus
                    main_component = nx.node_connected_component(G, lv_bus)
                    G = G.subgraph(main_component).copy()
                    self.logger.debug(f"Using component with LV bus {lv_bus}: {len(main_component)} nodes")
                else:
                    # Fallback to largest component
                    largest_cc = max(nx.connected_components(G), key=len)
                    G = G.subgraph(largest_cc).copy()
                    self.logger.debug(f"LV bus not in graph, using largest component: {len(largest_cc)} nodes")
            else:
                # No transformer info, use largest component
                largest_cc = max(nx.connected_components(G), key=len)
                G = G.subgraph(largest_cc).copy()
                self.logger.debug(f"No transformer found, using largest component: {len(largest_cc)} nodes")

        no_branches = calc.get_no_branches(G, net)

        try:
            avg_trafo_dis, max_trafo_dis = calc.get_distances_in_graph(net, G)
        except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
            self.logger.debug(f"Failed to calculate distances (disconnected component): {e}")
            avg_trafo_dis, max_trafo_dis = 0.0, 0.0
        except Exception as e:
            self.logger.warning(f"Failed to calculate distances in graph: {e}")
            avg_trafo_dis, max_trafo_dis = 0.0, 0.0

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

        # Initialize resistance-related variables with defaults
        max_no_of_households_of_a_branch = 0.0
        resistance = 0.0
        reactance = 0.0
        ratio = 0.0
        vsw_per_branch = 0.0
        max_vsw_of_a_branch = 0.0

        # Try to calculate resistance - may fail for non-radial networks
        try:
            (max_no_of_households_of_a_branch, resistance, reactance, ratio,
             max_vsw_of_a_branch) = calc.calc_resistance(net, G)
            vsw_per_branch = resistance / no_branches if no_branches > 0 else 0.0
        except (ValueError, KeyError, IndexError) as e:
            # Enhanced logging to diagnose resistance calculation failures
            net_id = getattr(net, 'name', 'unknown')
            self.logger.error(f"calc_resistance failed for network '{net_id}': {type(e).__name__}: {e}")
            self.logger.error(f"  Network stats: branches={no_branches}, loads={len(net.load)}, "
                            f"graph_nodes={len(G.nodes())}, graph_edges={len(G.edges())}")
            self.logger.error(f"  Consumer buses: {no_house_connections}, Connection buses: {no_connection_buses}")
            if hasattr(net, 'trafo') and len(net.trafo) > 0:
                lv_bus = net.trafo['lv_bus'].iloc[0]
                self.logger.error(f"  LV root bus: {lv_bus}, in graph: {lv_bus in G}")
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
        params = self.compute_metrics(net)

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
            Dictionary of computed metrics
        """
        metrics = self.compute_parameters_with_fallback(net)

        if output_path:
            if output_format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(metrics, f, indent=2)
                self.logger.info(f"Results saved to {output_path}")

            elif output_format == 'csv':
                df = pd.DataFrame([metrics])
                df.to_csv(output_path, index=False)
                self.logger.info(f"Results saved to {output_path}")

            elif output_format == 'excel':
                df = pd.DataFrame([metrics])
                df.to_excel(output_path, index=False)
                self.logger.info(f"Results saved to {output_path}")

            else:
                raise ValueError(f"Unsupported output format: {output_format}")

        return metrics

    def analyze_batch(
        self,
        networks_dir: Union[str, Path],
        output_csv: Union[str, Path],
        filename_parser: Optional[Callable[[str], Dict[str, Any]]] = None,
        pattern: str = "*.json",
        estimate_simultaneous_load: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> pd.DataFrame:
        """
        Analyze multiple networks from a directory and export to CSV.

        Parameters
        ----------
        networks_dir : str | Path
            Directory containing network JSON files
        output_csv : str | Path
            Path to output CSV file
        filename_parser : callable, optional
            Function to extract metadata from filename. Should return dict.
            If None, uses default parser for trafo_{id}.json pattern.
        pattern : str
            Glob pattern for matching files (default: "*.json")
        estimate_simultaneous_load : bool
            Whether to estimate simultaneous peak load
        progress_callback : callable, optional
            Function called with (current, total, filename) for progress tracking

        Returns
        -------
        pd.DataFrame
            DataFrame with metrics for all analyzed networks

        Examples
        --------
        >>> calc = MetricsCalculator()
        >>> df = calc.analyze_batch(
        ...     networks_dir='/data/subgrids',
        ...     output_csv='/data/metrics.csv'
        ... )
        >>> print(f"Analyzed {len(df)} networks")
        """
        networks_dir = Path(networks_dir)
        output_csv = Path(output_csv)

        if not networks_dir.exists():
            raise FileNotFoundError(f"Directory not found: {networks_dir}")

        # Use default parser if none provided
        if filename_parser is None:
            filename_parser = self._default_filename_parser

        rows: List[Dict[str, Any]] = []
        files = sorted(networks_dir.glob(pattern))
        total_files = len(files)

        if total_files == 0:
            self.logger.warning(f"No files matching '{pattern}' found in {networks_dir}")
            return pd.DataFrame()

        self.logger.info(f"Processing {total_files} networks from {networks_dir}")

        for idx, filepath in enumerate(files, 1):
            if progress_callback:
                progress_callback(idx, total_files, filepath.name)

            try:
                net = pp.from_json(str(filepath))
                params = self.compute_parameters_with_fallback(
                    net,
                    estimate_simultaneous_load=estimate_simultaneous_load
                )
                meta = filename_parser(filepath.name)
                rows.append({"file": filepath.name, **meta, **params})

            except Exception as e:
                self.logger.error(f"Failed to process {filepath.name}: {e}")
                meta = filename_parser(filepath.name)
                rows.append({"file": filepath.name, **meta, "error": str(e)})

        df = pd.DataFrame(rows)
        df.to_csv(output_csv, index=False)
        self.logger.info(f"Exported metrics for {len(df)} networks to {output_csv}")

        return df

    @staticmethod
    def _default_filename_parser(filename: str) -> Dict[str, Any]:
        """
        Default parser for network filenames.

        Expected patterns:
        - {netz}__trafo_{id}.json
        - trafo_{id}.json

        Parameters
        ----------
        filename : str
            Network filename

        Returns
        -------
        dict
            Dictionary with 'netznummer' and 'trafo_id' keys
        """
        pattern = re.compile(r"^(?:(?P<netz>\w{3})__)?trafo_(?P<tid>\d+)\.json$")
        match = pattern.match(filename)
        return {
            "netznummer": match.group("netz") if match else None,
            "trafo_id": match.group("tid") if match else None,
        }


def analyze_network(
    net: pp.pandapowerNet,
    output_path: Optional[str] = None,
    adapt_network: bool = True,
    zone_mapping: Optional[Dict[str, str]] = None,
    **adapter_kwargs
) -> Dict[str, Any]:
    """
    Convenience function to analyze an external network.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network to analyze
    output_path : str, optional
        Path to save analysis results
    adapt_network : bool
        Whether to adapt the network structure first
    zone_mapping : dict, optional
        Zone mapping for adaptation
    **adapter_kwargs
        Additional arguments for network adaptation

    Returns
    -------
    dict
        Dictionary of computed metrics

    Examples
    --------
    >>> import pandapower as pp
    >>> net = pp.from_json('/data/SWD_V7.json')
    >>> results = analyze_network(
    ...     net,
    ...     output_path='/data/SWD_V7_analysis.json',
    ...     zone_mapping={'residential': 'Residential'}
    ... )
    >>> print(f"Cable length: {results['cable_length_km']:.2f} km")
    """
    if adapt_network:
        from .network_adapter import adapt_network as adapt_net
        net = adapt_net(net, zone_mapping=zone_mapping, **adapter_kwargs)

    calculator = MetricsCalculator()
    return calculator.analyze_and_export(net, output_path)


def analyze_network_batch(
    networks_dir: Union[str, Path],
    output_csv: Union[str, Path],
    filename_parser: Optional[Callable[[str], Dict[str, Any]]] = None,
    pattern: str = "*.json",
    estimate_simultaneous_load: bool = True
) -> pd.DataFrame:
    """
    Convenience function to analyze multiple networks from a directory.

    Parameters
    ----------
    networks_dir : str | Path
        Directory containing network JSON files
    output_csv : str | Path
        Path to output CSV file
    filename_parser : callable, optional
        Function to extract metadata from filename
    pattern : str
        Glob pattern for matching files (default: "*.json")
    estimate_simultaneous_load : bool
        Whether to estimate simultaneous peak load

    Returns
    -------
    pd.DataFrame
        DataFrame with metrics for all analyzed networks

    Examples
    --------
    >>> df = analyze_network_batch(
    ...     networks_dir='/data/subgrids',
    ...     output_csv='/data/metrics.csv'
    ... )
    >>> print(f"Analyzed {len(df)} networks")
    >>> print(f"Average cable length: {df['cable_length_km'].mean():.2f} km")
    """
    calculator = MetricsCalculator()
    return calculator.analyze_batch(
        networks_dir=networks_dir,
        output_csv=output_csv,
        filename_parser=filename_parser,
        pattern=pattern,
        estimate_simultaneous_load=estimate_simultaneous_load
    )

