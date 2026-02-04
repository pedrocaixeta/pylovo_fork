"""
Topology and load-aggregation metrics for LV distribution grids (validation_swf workflow).

Purpose
- Compute descriptive parameters for radial low-voltage (LV) grids modeled in pandapower.
- Support PLZ-wide aggregation and per-grid metrics used in validation_swf and clustering.

Key ideas
- Treat the LV transformer LV bus ("LVbus") as the root of a radial tree.
- Respect operational topology by building graphs with respect_switches=True.
- Aggregate consumer loads using simultaneity factors per category (Residential/Public/Commercial).
- Provide impedance-weighted proxies that correlate with voltage drop ("vsw"-like metrics).

Outputs include counts (buses, loads), distances to trafo (avg/max), cable lengths,
transformer sizing, simultaneity-based peak loads, and resistance/reactance proxies.

Notes
- Several methods assume radial structure and a unique upstream line per bus.
- Geographic vs projected coordinates are auto-detected for proximity metrics.
"""

import json
import math
import statistics
from math import radians
from typing import Tuple, Dict, Any, List

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pandapower as pp
import pandapower.topology as top
from sklearn.metrics.pairwise import haversine_distances

import pylovo.database.database_client as dbc
from pylovo import utils
from pylovo.config_loader import *
from pylovo.analysis.powerflow_analysis import run_powerflow
from pylovo.utils import oneSimultaneousLoad
from pylovo.database.config_table_structure import CREATE_QUERIES

class ParameterCalculator:
    """Calculate and persist LV grid parameters at PLZ and per-grid levels.

    Scope
    1) PLZ level: aggregate statistics across all local grids inside a PLZ
       (counts, cable length per type, trafo-size vs distance/load lookup tables).
    2) Grid level: detailed parameters per local grid (kcid, bcid) for clustering.

    Attributes:
        plz (int): Postcode area ID
        bcid (int): Building cluster ID (negative bcid implies an OSM-only transformer)
        kcid (int): K-means cluster ID of the grid
        version_id (str): Analysis version taken from configuration
        dbc (DatabaseClient): Database client used for I/O of pandapower nets and parameters
        lvbus_keyword (str): substring to identify the LV root bus
        consumer_bus_keyword (str): substring to identify consumer buses
        connection_bus_keyword (str): substring to identify internal connection buses
    """

    def __init__(self, keyword_lvbus: str = "LVbus", keyword_consumer_bus: str = "Consumer Nodebus",
                 keyword_connection_bus: str = "Connection Nodebus"):
        self.dbc = dbc.DatabaseClient()
        self.version_id = VERSION_ID
        # Configurable keywords for bus identification across different datasets
        self.lvbus_keyword = keyword_lvbus
        self.consumer_bus_keyword = keyword_consumer_bus
        self.connection_bus_keyword = keyword_connection_bus
        self.plz = None
        self.kcid = None
        self.bcid = None

    def calc_parameters_per_plz(self, plz: int = None):
        """Compute and store PLZ-wide parameters.

        Args:
            plz (int): Postcode area ID

        Side effects:
            - Reads all nets of the PLZ from the database.
            - Writes aggregated per-PLZ results and sets analysis flags.
            - Skips PLZs already analyzed.
        """
        self.plz = plz
        grid_generated = self.dbc.is_grid_generated(self.plz)
        if not grid_generated:
            self.dbc.logger.info(f"Grid for the postcode area {self.plz} is not generated, yet. Generate it first.")
            return
        grid_analysed = self.dbc.is_grid_analyzed(self.plz)
        if grid_analysed:
            self.dbc.logger.info(f"Grid for the postcode area {self.plz} has already been analyzed.")
            return

        try:
            self.dbc.logger.info(f"PLZ {self.plz}: start basic result analysis")
            self.analyse_basic_parameters_per_plz(self.plz)
            self.dbc.logger.info(f"PLZ {self.plz}: start cable counting")
            self.analyse_cables_per_plz(self.plz)
            self.dbc.logger.info(f"PLZ {self.plz}: start per-trafo analysis")
            self.analyse_trafo_parameters_per_plz(self.plz)
            self.dbc.logger.info(f"PLZ {self.plz}: result analysis finished")
            self.dbc.conn.commit()
        except Exception as e:
            self.dbc.logger.error(f"Error during analysis for PLZ {self.plz}: {e}")
            self.dbc.logger.info(f"Skipped PLZ {self.plz} due to analysis error.")
            self.dbc.delete_plz_from_sample_set_table(str(CLASSIFICATION_VERSION), self.plz)
            raise e

    def calc_parameters_per_grid(self, plz: int = None):
        """Compute and store per-grid parameters for all grids of an analyzed PLZ.

        Args:
            plz (int): Postcode area ID

        Note:
            Ensures PLZ-level metrics exist first (used for per-PLZ lookups).
        """
        self.plz = plz
        grid_analysed = self.dbc.is_grid_analyzed(self.plz)
        if not grid_analysed:
            self.dbc.logger.info(
                f"PLZ parameters for the postcode area {self.plz} missing. Please run calc_parameters_per_plz() first.")
            return

        # Remove the early return that skips the entire PLZ if ANY parameters exist.
        # Instead, verify per grid if it needs calculation.
        
        cluster_list = self.dbc.get_list_from_plz(self.plz)
        total_grids = len(cluster_list)
        print(f"Checking {total_grids} grids for PLZ {self.plz}...")

        skipped = 0
        calculated = 0

        for kcid, bcid in cluster_list:
            # Check if this specific grid already has parameters
            try:
                if self.dbc.has_clustering_parameters(self.plz, kcid, bcid):
                     skipped += 1
                     continue
                
                print(f"Calculating parameters for grid {bcid}, {kcid}")
                self.calc_grid_parameters(bcid, kcid)
                calculated += 1
                
            except Exception as e:
                self.dbc.logger.error(f"Failed to calculate/insert parameters for {kcid}, {bcid}: {e}")
        
        print(f"Finished PLZ {self.plz}. Calculated: {calculated}, Skipped (already existed): {skipped}.")

        print(f"Finished PLZ {self.plz}. Calculated: {calculated}, Skipped (already existed): {skipped}.")

    def preprocess_net_for_pf(self, net: pp.pandapowerNet):
        """
        Preprocess net for power flow:
        - Fix zero impedance lines.
        - Ensure connectivity data structures are ready (though runpp does that).
        """
        # Fix zero impedance/length
        if not net.line.empty:
             mask_zero = (net.line.r_ohm_per_km == 0) & (net.line.x_ohm_per_km == 0)
             if mask_zero.any():
                 net.line.loc[mask_zero, "r_ohm_per_km"] = 1e-6
                 net.line.loc[mask_zero, "x_ohm_per_km"] = 1e-6

             # Also zero length?
             mask_len = net.line.length_km <= 0
             if mask_len.any():
                  net.line.loc[mask_len, "length_km"] = 0.001

    def calculate_comparison_metrics(self, net: pp.pandapowerNet, buildings_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Calculate grid parameters specifically for comparison.
        Refactored to reuse core logic with adaptable node identification.
        """

        # 1. Identify Key Nodes (Root & Consumers)
        # Try PyLovo naming conventions first
        is_pylovo = "name" in net.bus.columns and net.bus["name"].str.contains(self.lvbus_keyword).any()

        try:
            if is_pylovo:
                # Use existing keyword-based lookup
                root_idx = self.get_root(net)
                # Consumers = "Consumer Nodebus"
                consumer_mask = net.bus["name"].str.contains(self.consumer_bus_keyword)
                consumer_buses = net.bus[consumer_mask].index.tolist()

                house_connections = len(consumer_buses)

            else:
                # Real Grids / Generic Fallback
                # Root: First LV bus of transformer, or ext_grid bus
                if not net.trafo.empty:
                    root_idx = net.trafo['lv_bus'].iloc[0]
                elif not net.ext_grid.empty:
                    root_idx = net.ext_grid['bus'].iloc[0]
                else:
                    # No source?
                    root_idx = net.bus.index[0]

                # Consumers: All buses with loads
                # Note: In real grids, one bus might have multiple loads or one aggregated load.
                # We count loads as connections? Or buses with loads?
                # User complaint: "value for house_connections changes" -> implying count of loads vs count of buses.
                # PyLovo 'house_connections' = count of buses named "Consumer Nodebus".
                # For Real Grids, let's treat every Load as a connection.
                consumer_buses = net.load['bus'].unique().tolist()
                house_connections = len(net.load)

            # 2. Structural Metrics (Reusing helpers with explicit nodes)
            G = pp.topology.create_nxgraph(net, respect_switches=True)

            # Feeder Lines (No. Branches)
            # Pass explicit root to avoid internal get_root() calling keyword search again if we want to be safe,
            # BUT get_no_branches currently calls get_root(net) internally.
            # We need to refactor get_no_branches to accept root_idx.
            feeder_lines = self.get_no_branches(G, net, root_idx=root_idx)

            # Avg Trafo Distance
            # Valid consumer buses only (must be in graph)
            valid_consumers = [b for b in consumer_buses if b in G]
            avg_trafo_distance, _ = self._calculate_path_lengths(G, root_idx, valid_consumers)

        except Exception as e:
            self.dbc.logger.error(f"Error calculating structural metrics: {e}")
            import traceback
            traceback.print_exc()
            feeder_lines = 0
            house_connections = len(net.load)
            avg_trafo_distance = 0.0

        cable_length = net.line[net.line.in_service]["length_km"].sum()

        # 3. Max Voltage Drop
        max_voltage_drop = 0.0

        # Preprocess
        self.preprocess_net_for_pf(net)

        try:
             # Check connectivity: select component with ext_grid
             mg = pp.topology.create_nxgraph(net, respect_switches=True)
             if not net.ext_grid.empty:
                  ext_bus = net.ext_grid.bus.iloc[0]
                  # Components
                  # If disconnected, we might want to drop disconnected buses or just warn
                  # For calculation, pandapower usually handles it unless Z=0
                  pass

             # Use robust run_powerflow
             success = run_powerflow(net)
             if success:
                 vm_pu = net.res_bus.vm_pu
                 # Consider only voltage at consumer buses or all buses?
                 # Usually drop at endpoints is what matters.
                 if is_pylovo:
                      # Filter for consumer buses to match PyLovo logic?
                      # Or just min of all? Usually min is at end of line.
                      max_voltage_drop = 1.0 - vm_pu.min()
                 else:
                      max_voltage_drop = 1.0 - vm_pu.min()

                 if np.isnan(max_voltage_drop):
                     max_voltage_drop = 0.0
             else:
                 max_voltage_drop = np.nan

        except Exception as e:
             # Power flow failed
             self.dbc.logger.warning(f"Power flow failed: {e}")
             max_voltage_drop = np.nan

        return {
            "feeder_lines": int(feeder_lines),
            "house_connections": int(house_connections),
            "cable_length": float(cable_length),
            "avg_trafo_distance": float(avg_trafo_distance),
            "max_voltage_drop": float(max_voltage_drop),
        }

    def calc_comparison_parameters_for_plz(self, plz: int):
        """
        Calculate and store comparison parameters for all grids in a PLZ.
        Populates 'grid_parameters' table.
        """
        self.plz = plz

        # Ensure table exists
        create_query = CREATE_QUERIES["grid_parameters"]
        self.dbc.cur.execute(create_query)
        self.dbc.conn.commit()

        grids = self.dbc.get_list_from_plz(plz)
        print(f"Calculating comparison parameters for {len(grids)} grids in PLZ {plz}...")

        metrics_list = []

        for kcid, bcid in grids:
            try:
                # 1. Load Grid
                net = self.dbc.read_net_db(plz, kcid, bcid)
                self.dbc.cur.execute("SELECT grid_result_id FROM grid_result WHERE plz=%s AND kcid=%s AND bcid=%s AND version_id=%s", (plz, kcid, bcid, self.version_id))
                grid_result_id = self.dbc.cur.fetchone()[0]

                # 2. Apply Simultaneity
                # Logic: P_sim = P_max * oneSimultaneousLoad(1, n_loads, sim_factor)
                # Synthetic grids usually store max power in p_mw or max_p_mw
                # We assume p_mw is peak/installed, and we apply factor.
                n_loads = len(net.load)
                if n_loads > 0:
                    sim_factor = oneSimultaneousLoad(1.0, n_loads, 0.07) # Residential default
                    if "max_p_mw" in net.load.columns:
                         net.load["p_mw"] = net.load["max_p_mw"] * sim_factor
                    else:
                         net.load["p_mw"] = net.load["p_mw"] * sim_factor

                # 3. Calculate Metrics
                params = self.calculate_comparison_metrics(net)
                params["grid_result_id"] = grid_result_id
                metrics_list.append(params)

                # 4. Insert into DB
                query = """
                    INSERT INTO grid_parameters (grid_result_id, feeder_lines, house_connections, cable_length, avg_trafo_distance, max_voltage_drop, trafo_capacity, mean_line_capacity)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (grid_result_id) DO UPDATE SET
                    feeder_lines = EXCLUDED.feeder_lines,
                    house_connections = EXCLUDED.house_connections,
                    cable_length = EXCLUDED.cable_length,
                    avg_trafo_distance = EXCLUDED.avg_trafo_distance,
                    max_voltage_drop = EXCLUDED.max_voltage_drop;
                """
                self.dbc.cur.execute(query, (
                    grid_result_id,
                    params["feeder_lines"],
                    params["house_connections"],
                    params["cable_length"],
                    params["avg_trafo_distance"],
                    params["max_voltage_drop"],
                    params["trafo_capacity"],
                    params["mean_line_capacity"]
                ))
            except Exception as e:
                self.dbc.logger.error(f"Error processing grid {kcid}_{bcid}: {e}")
                self.dbc.conn.rollback()

            # Commit after each grid to enable progress monitoring and avoid long locks
            self.dbc.conn.commit()

        self.dbc.conn.commit()

        # 5. Export Synthetic Metrics to CSV
        if metrics_list:
            df = pd.DataFrame(metrics_list)
            out_dir = Path("validation/metrics")
            out_dir.mkdir(parents=True, exist_ok=True)
            csv_path = out_dir / "synthetic_grid_metrics.csv"
            df.to_csv(csv_path, index=False)
            print(f"Saved synthetic grid metrics to {csv_path}")

    def calc_grid_parameters(self, bcid: int, kcid: int) -> None:
        """Compute parameters for a single local grid and persist them.

        Args:
            bcid (int): Building cluster ID
            kcid (int): Grid cluster ID

        Writes a record to the clustering-parameters table including metadata
        (plz, bcid, kcid, version, osm_trafo flag).
        """
        self.bcid = bcid
        self.kcid = kcid
        osm_trafo = self.has_osm_trafo()

        net = self.dbc.read_net_db(self.plz, self.kcid, self.bcid)
        params = self.compute_parameters(net)
        params.update({
            "version_id": self.version_id,
            "plz": self.plz,
            "bcid": self.bcid,
            "kcid": self.kcid,
            "osm_trafo": bool(osm_trafo)
        })

        self.dbc.insert_clustering_parameters(params)

    def compute_parameters(self, net: pp.pandapowerNet) -> Dict[str, Any]:
        """Compute a consistent set of topology and load metrics for one grid.

        Args:
            net (pp.pandapowerNet): The pandapower network model.

        Returns:
            Dict[str, Any]: A dictionary containing calculated metrics/parameters.
        """
        no_house_connections = self.get_no_of_buses(net, self.consumer_bus_keyword)
        no_connection_buses = self.get_no_of_buses(net, self.connection_bus_keyword)
        no_households = self.get_no_households(net)
        max_power_mw = self.get_max_power(net)

        no_household_equ = max_power_mw * 1000.0 / PEAK_LOAD_HOUSEHOLD
        cable_length_km = self.get_cable_length(net)
        cable_len_per_house = cable_length_km / no_house_connections if no_house_connections > 0 else 0.0

        # Build operational topology (critical for DSO radial operation)
        G = pp.topology.create_nxgraph(net, respect_switches=True)
        no_branches = self.get_no_branches(G, net)
        avg_trafo_dis, max_trafo_dis = self.get_distances_in_graph(net, G)

        # Branch-normalized counts
        if no_branches > 0:
            no_house_connections_per_branch = no_house_connections / no_branches
            no_households_per_branch = max_power_mw * 1000.0 / (PEAK_LOAD_HOUSEHOLD * no_branches)
        else:
            no_house_connections_per_branch = 0.0
            no_households_per_branch = 0.0

        transformer_mva = self.get_trafo_power(net)
        house_distance_km = self.calc_avg_house_distance(net)
        simultaneous_peak_load_mw = self.get_simultaneous_peak_load(transformer_mva, max_trafo_dis)

        # Calculate resistance and voltage proxies
        (max_no_of_households_of_a_branch, resistance, reactance, ratio, max_vsw_of_a_branch) = \
            self.calc_impedance_metrics(net, G)

        vsw_per_branch = resistance / no_branches if no_branches > 0 else 0.0

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

    def get_parameters_as_dataframe(self, net: pp.pandapowerNet) -> pd.DataFrame:
        """Return parameters as a one-row DataFrame."""
        params = self.compute_parameters(net)
        return pd.DataFrame([params], columns=CLUSTERING_PARAMETERS)

    def get_simultaneous_peak_load(self, transformer_mva: float, max_trafo_dis: float) -> float:
        """Lookup coincident peak load for a transformer size and max path distance.

        Args:
            transformer_mva (float): Transformer rating in MVA.
            max_trafo_dis (float): Maximum distance from transformer to any load in km.

        Returns:
            float: Simultaneous peak load in MW.
        """
        data_list, _, _ = self.dbc.read_per_trafo_dict(self.plz)
        transformer_type_str = str(int(transformer_mva * 1000))
        max_trafo_distance_list = data_list[3].get(transformer_type_str, [])

        target_dist = max_trafo_dis * 1000
        if target_dist in max_trafo_distance_list:
            sim_load_index = max_trafo_distance_list.index(target_dist)
            simultaneous_peak_load_mw = data_list[2][transformer_type_str][sim_load_index] / 1000
            return simultaneous_peak_load_mw
        return 0.0

    def get_trafo_power(self, pandapower_net: pp.pandapowerNet) -> float:
        """Transformer rating in MVA (assumes exactly one LV transformer). Raises if missing."""
        if pandapower_net.trafo.empty:
            raise ValueError(f"No transformer found for PLZ {self.plz}, kcid {self.kcid}, bcid {self.bcid}.")
        return pandapower_net.trafo["sn_mva"].iloc[0]

    def has_osm_trafo(self) -> bool:
        """True if the grid's transformer originates from OSM data (bcid < 0)."""
        return self.bcid < 0

    def get_max_power(self, pandapower_net: pp.pandapowerNet) -> float:
        """Sum of installed maximum active power (MW) over all loads."""
        return pandapower_net.load["max_p_mw"].sum()

    def get_no_households(self, pandapower_net: pp.pandapowerNet) -> int:
        """Number of load elements (proxy for number of households)."""
        return len(pandapower_net.load)

    def get_no_of_buses(self, pandapower_net: pp.pandapowerNet, bus_description: str) -> int:
        """Count buses whose name contains a given description (substring match)."""
        return pandapower_net.bus["name"].str.contains(bus_description).sum()

    def get_cable_length(self, pandapower_net: pp.pandapowerNet) -> float:
        """Total circuit length in km across all line elements."""
        return pandapower_net.line["length_km"].sum()

    def calc_avg_house_distance(self, pandapower_net: pp.pandapowerNet) -> float:
        """Spatial neighbor metric for consumer buses.

        Calculates the median of the mean distance to the 4 nearest neighbors for each consumer bus.
        Auto-detects coordinate system.
        """
        bus = pandapower_net.bus

        # Check for valid geometries
        if bus["geo"].isna().all():
            return 0.0

        # Extract coordinates
        geometries = []
        for geo_str in bus["geo"].dropna():
            try:
                geo_dict = json.loads(geo_str)
                geometries.append(geo_dict["coordinates"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if len(geometries) < 2:
            return 0.0

        # Convert to numpy array
        coords = np.array(geometries)

        # Detect coordinate system
        is_geographic = (coords[:, 0].min() >= -180 and coords[:, 0].max() <= 180 and
                         coords[:, 1].min() >= -90 and coords[:, 1].max() <= 90)

        if is_geographic:
            # Convert to radians for haversine
            coords_rad = np.radians(coords)
            dis_mat = haversine_distances(coords_rad, coords_rad) * 6371.0 # Earth radius km
        else:
            from scipy.spatial.distance import cdist
            dis_mat = cdist(coords, coords, metric='euclidean') / 1000.0 # meters to km

        # Calculate average distance to 4 nearest neighbors (excluding self)
        # Sort each row, take indices 1 to 5 (0 is self with dist 0)
        # If fewer than 5 points, take what we have
        k = min(len(dis_mat) - 1, 4)
        if k == 0:
            return 0.0

        dis_mat.sort(axis=1)
        avg_dists = dis_mat[:, 1:k+1].mean(axis=1)

        return float(np.median(avg_dists))

    def get_root(self, pandapower_net: pp.pandapowerNet) -> int:
        """Return LV root bus index."""
        # Try finding by keyword
        if "name" in pandapower_net.bus.columns:
            root = pandapower_net.bus[pandapower_net.bus["name"].str.contains(self.lvbus_keyword, na=False)]
            if not root.empty:
                return root.index[0]

        # Fallback: Trafo LV bus
        if not pandapower_net.trafo.empty:
             return pandapower_net.trafo["lv_bus"].iloc[0]

        raise ValueError(f"No LV bus found using keyword '{self.lvbus_keyword}' and no trafo found.")

    def get_no_branches(self, networkx_graph: nx.Graph, pandapower_net: pp.pandapowerNet, root_idx: int = None) -> int:
        """Approximate number of main feeders from the LV bus. 
        Handles Cable Distribution Cabinets (KVS) as splitters if directly connected."""
        if root_idx is None:
            root = self.get_root(pandapower_net)
        else:
            root = root_idx

        if root not in networkx_graph:
            return 0
            
        root_degree = networkx_graph.degree[root]
        
        # If single feeder, checking if it splits immediately at a KVS
        # Or even if multiple feeders, check if any go to a KVS
        if root_degree > 0:
            branches = 0
            neighbors = list(networkx_graph.neighbors(root))
            
            # Helper to check if edge is a transformer (don't count MV connection)
            def is_trafo(u, v):
                mask = ((pandapower_net.trafo["hv_bus"] == u) & (pandapower_net.trafo["lv_bus"] == v)) | \
                       ((pandapower_net.trafo["hv_bus"] == v) & (pandapower_net.trafo["lv_bus"] == u))
                return not mask.empty and mask.any()

            for n in neighbors:
                if is_trafo(root, n):
                    continue
                
                # Check if neighbor is a KVS
                bus_name = str(pandapower_net.bus.at[n, "name"])
                if "NS_KVS" in bus_name:
                    # It is a KVS. Count its branches (degree - 1 for incoming)
                    kvs_degree = networkx_graph.degree[n]
                    # If KVS is a dead end (degree 1), it counts as 1 branch (the KVS itself) or 0? 
                    # Usually 0 meaningful feeders if no outgoing lines. But let's say 0.
                    # If degree 2, 1 outgoing.
                    branches += max(kvs_degree - 1, 0)
                else:
                    branches += 1
            
            # If branches is 0 but we have neighbors (and not just MV), fallback to degree-1 (trafo) 
            # (Logic above handles MV detection via is_trafo)
            return branches

        return 0

    def get_distances_in_graph(self, pandapower_net: pp.pandapowerNet, networkx_graph: nx.Graph, root_idx: int = None, leaves: List[int] = None) -> Tuple[float, float]:
        """Average and maximum weighted distances (km) from transformer to consumer buses."""
        if root_idx is None:
            root = self.get_root(pandapower_net)
        else:
            root = root_idx

        if leaves is None:
             if "name" in pandapower_net.bus.columns:
                 leaves = pandapower_net.bus[pandapower_net.bus["name"].str.contains(self.consumer_bus_keyword, na=False)].index
             else:
                 leaves = []
        
        if len(leaves) == 0:
            return 0.0, 0.0

        return self._calculate_path_lengths(networkx_graph, root, leaves)

    def _calculate_path_lengths(self, graph: nx.Graph, source: int, targets: List[int]) -> Tuple[float, float]:
        """Helper to calculate path lengths from source to multiple targets."""
        path_lengths = []
        for target in targets:
            if target not in graph or source not in graph:
                continue
            try:
                length = nx.dijkstra_path_length(graph, source, target, weight='weight')
                path_lengths.append(length)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

        if not path_lengths:
            return 0.0, 0.0

        return sum(path_lengths) / len(path_lengths), max(path_lengths)

    def calc_impedance_metrics(self, pandapower_net: pp.pandapowerNet, networkx_graph: nx.Graph) -> Tuple[float, float, float, float, float]:
        """Impedance-weighted proxies aggregated along consumer paths."""
        df_load = pandapower_net.load
        # Household Equivalents (HE)
        # Using per-bus HE accumulation
        df_vsw = df_load.groupby("bus")["max_p_mw"].sum() * 1000.0 / PEAK_LOAD_HOUSEHOLD
        df_vsw = df_vsw.reset_index(name="household_equivalents").rename(columns={"bus": "house_connection"})

        # Augment lines with simultaneity factors
        df_line = self._augment_line_table_with_simultaneity(pandapower_net, networkx_graph)

        root = self.get_root(pandapower_net)

        results = []

        # Iterate over each consumer bus
        for _, row in df_vsw.iterrows():
            house_conn = row["house_connection"]
            he = row["household_equivalents"]

            try:
                path = nx.shortest_path(networkx_graph, source=root, target=house_conn)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            
            # Identify branch
            # Logic update: If first hop is a KVS, split branches there.
            if len(path) >= 2:
                first_hop_name = str(pandapower_net.bus.at[path[1], "name"])
                if "NS_KVS" in first_hop_name and len(path) >= 3:
                     # Treat the link KVS->NextNode as the branch identifier
                     branch = tuple(sorted(path[1:3]))
                else:
                     branch = tuple(sorted(path[:2]))
            else:
                branch = None
            
            # Calculate impedance along path
            r_sum = 0.0
            x_sum = 0.0

            for i in range(len(path) - 1):
                u, v = path[i], path[i+1]
                # Find line data
                line_data = self._get_line_data(df_line, u, v)
                if line_data is None:
                    continue

                length_km = line_data["length_km"]
                sim_factor = line_data.get("sim_factor_cumulated", 1.0)

                r_sum += he * length_km * line_data["r_ohm_per_km"] * sim_factor
                x_sum += he * length_km * line_data["x_ohm_per_km"]

            results.append({
                "branch": branch,
                "household_equivalents": he,
                "resistance": r_sum,
                "reactance": x_sum
            })

        if not results:
             return 0.0, 0.0, 0.0, 0.0, 0.0

        df_res = pd.DataFrame(results)

        max_he_branch = df_res.groupby("branch")["household_equivalents"].sum().max() if "branch" in df_res else 0.0
        total_resistance = df_res["resistance"].sum()
        total_reactance = df_res["reactance"].sum()
        ratio = total_resistance / total_reactance if total_reactance > 0 else 0.0
        max_vsw_branch = df_res.groupby("branch")["resistance"].sum().max() if "branch" in df_res else 0.0

        return max_he_branch, total_resistance, total_reactance, ratio, max_vsw_branch

    def _get_line_data(self, df_line: pd.DataFrame, u: int, v: int) -> Dict[str, Any]:
        """Find line between u and v in dataframe."""
        mask = ((df_line["from_bus"] == u) & (df_line["to_bus"] == v)) | \
               ((df_line["from_bus"] == v) & (df_line["to_bus"] == u))
        subset = df_line[mask]
        if subset.empty:
            return None
        return subset.iloc[0].to_dict()

    def _augment_line_table_with_simultaneity(self, net: pp.pandapowerNet, graph: nx.Graph) -> pd.DataFrame:
        """Augment line table with simultaneity/load aggregation metadata."""
        # Initialize columns
        df_line = net.line.copy()

        # Load Simultaneity Definitions
        sim_defs = pd.DataFrame.from_dict(SIM_FACTOR, orient='index', columns=['sim_factor'])
        sim_defs.index.name = 'description'
        sim_defs.reset_index(inplace=True)

        # 1. Level 1: Consumer Buses - Calculate local loads and counts
        # Join loads with buses/zones
        loads = net.load.copy()

        # Merge zone info from bus table
        # net.load.bus references bus index. net.bus.index is the bus index.
        # We need 'zone' from net.bus
        loads = loads.merge(net.bus[['zone']], left_on='bus', right_index=True, how='left')

        # Remap aliases to standard categories
        if 'zone' in loads.columns:
            loads['zone'] = loads['zone'].replace(['MFH', 'SFH', 'AB', 'TH'], 'Residential')
        else:
             # Fallback if zone is missing? Or error?
             self.dbc.logger.warning("Zone column missing in bus table, assuming Residential.")
             loads['zone'] = 'Residential'

        # Group by bus and zone
        bus_zone_stats = loads.groupby(['bus', 'zone']).agg(
            count=('name', 'count'),
            max_p_mw=('max_p_mw', 'sum')
        ).reset_index()

        # Merge with simulation factors
        bus_zone_stats = bus_zone_stats.merge(sim_defs, left_on='zone', right_on='description', how='left')

        # Calculate simultaneous load per group
        # Fix: passing scalars to oneSimultaneousLoad by applying row-wise
        bus_zone_stats['sim_load'] = bus_zone_stats.apply(
            lambda r: utils.oneSimultaneousLoad(1, r['count'], r['sim_factor']) * r['max_p_mw'], axis=1
        )

        # Calculate level 1 simultaneity factor
        bus_zone_stats['sim_factor_level1'] = bus_zone_stats.apply(
             lambda r: utils.oneSimultaneousLoad(1, r['count'], r['sim_factor']), axis=1
        )

        # Annotate upstream lines (Level 1)
        # We need to map each bus to its upstream line.
        # This assumes radiality: each bus has one upstream line.

        # Prepare result structures
        line_stats = {} # line_index -> stats dict

        for _, row in bus_zone_stats.iterrows():
            bus = row['bus']
            # Find incident lines
            incident_lines = df_line[(df_line['from_bus'] == bus) | (df_line['to_bus'] == bus)]
            if incident_lines.empty:
                continue

            # Heuristic: The incident line is the upstream one.
            # In a radial tree where flow goes from root, the upstream line is the one closer to root.
            # But here we just attach to the unique line (if it's a leaf endpoint).
            # If it's not a leaf, we need to be careful.
            # However, logic in original code just taking the first incident line seems to be the logic for "upstream line incident to consumer bus".
            # Usually consumer buses are leaves or inline on a feeder.

            # We assume the line to annotate is the one connecting to this bus.
            line_idx = incident_lines.index[0]

            if line_idx not in line_stats:
                line_stats[line_idx] = {'sim_load': 0.0, 'peak_load': 0.0}

            line_stats[line_idx]['sim_load'] += row['sim_load']
            line_stats[line_idx]['peak_load'] += row['max_p_mw']

        # Apply Level 1 stats
        for idx, stats in line_stats.items():
            df_line.at[idx, 'sim_load'] = stats['sim_load']
            peak = stats['peak_load']
            if peak > 0:
                df_line.at[idx, 'sim_factor_cumulated'] = stats['sim_load'] / peak
            else:
                 df_line.at[idx, 'sim_factor_cumulated'] = 0.0

        # 2. Level 2: Propagate Upstream (Connection Buses)
        # This part requires traversing the tree from leaves to root.
        # Or sorting buses by distance from root descending.

        try:
             root = self.get_root(net)
        except ValueError:
            return df_line # Cannot propagate without root

        # Get all buses sorted by distance from root (descending)
        # to ensure we process children before parents
        if root in graph:
            dists = nx.shortest_path_length(graph, source=root)
            sorted_buses = sorted(dists.keys(), key=lambda b: dists[b], reverse=True)

            # Map lines to [u, v] for easier lookup
            # Since edges in graph are undirected, we need to know direction flow
            # In radial tree rooted at root, for edge (u, v) where dist(u) < dist(v), flow is u -> v.

            # Initialize accumulation if not present
            if 'sim_load' not in df_line.columns:
                 df_line['sim_load'] = 0.0
            if 'sim_factor_cumulated' not in df_line.columns:
                 df_line['sim_factor_cumulated'] = 1.0 # default

            # We need to aggregate loads per category to correctly recalculate simultaneity
            # So we need to track counts/loads per category per line.

            # This is complex to reimplement fully without the exact category tracking logic
            # from the original code.
            # However, the original code had distinct columns:
            # no_commercial, load_commercial_mw, etc.

            # Let's keep it simple and stick to what the original code did but cleaner.
            pass # The original implementation was very specific about categories.

            # To respect "clearly understandable functions", I should probably
            # keep the logic but structure it better.

            # Re-implementing the category aggregation:
            # We need columns for each category on df_line
            cats = ['Commercial', 'Public', 'Residential']
            for cat in cats:
                 df_line[f'no_{cat}'] = 0
                 df_line[f'load_{cat}_mw'] = 0.0

            # Fill from Level 1 stats (which we computed earlier)
            # We need to re-iterate bus_zone_stats to populate these specific columns
            for _, row in bus_zone_stats.iterrows():
                bus = row['bus']
                cat = row['zone']
                if cat not in cats: continue

                incident_lines = df_line[(df_line['from_bus'] == bus) | (df_line['to_bus'] == bus)]
                if incident_lines.empty: continue
                line_idx = incident_lines.index[0]

                df_line.at[line_idx, f'no_{cat}'] += row['count']
                df_line.at[line_idx, f'load_{cat}_mw'] += row['max_p_mw']

            # Now propagate upstream
            # For each bus in sorted order (farthest first)
            for bus in sorted_buses:
                if bus == root: continue

                # Find line feeding this bus (upstream line)
                # And lines fed by this bus (downstream lines)

                # In a tree, there is exactly one upstream neighbor (closer to root)
                pred = list(graph.neighbors(bus))
                # Identify parent (closer to root)
                parent = None
                children = []
                for n in pred:
                    if dists[n] < dists[bus]:
                        parent = n
                    else:
                        children.append(n)

                if parent is None: continue # Should generally not happen except for root or disconnected

                # Find upstream line index
                upstream_line_mask = ((df_line["from_bus"] == parent) & (df_line["to_bus"] == bus)) | \
                                     ((df_line["from_bus"] == bus) & (df_line["to_bus"] == parent))
                if upstream_line_mask.sum() == 0: continue
                upstream_idx = upstream_line_mask.idxmax()

                # Aggregate from downstream lines
                for child in children:
                     downstream_line_mask = ((df_line["from_bus"] == bus) & (df_line["to_bus"] == child)) | \
                                            ((df_line["from_bus"] == child) & (df_line["to_bus"] == bus))
                     if downstream_line_mask.sum() == 0: continue
                     down_idx = downstream_line_mask.idxmax()

                     # Add child's totals to parent's totals
                     for cat in cats:
                         df_line.at[upstream_idx, f'no_{cat}'] += df_line.at[down_idx, f'no_{cat}']
                         df_line.at[upstream_idx, f'load_{cat}_mw'] += df_line.at[down_idx, f'load_{cat}_mw']

                # Update simultaneity for upstream line based on aggregated values
                total_sim_load = 0.0
                total_peak = 0.0

                for cat in cats:
                    cnt = df_line.at[upstream_idx, f'no_{cat}']
                    load_mw = df_line.at[upstream_idx, f'load_{cat}_mw']
                    sim_f = SIM_FACTOR.get(cat, 1.0)

                    if cnt > 0 and load_mw > 0:
                        sim_load = utils.oneSimultaneousLoad(load_mw, cnt, sim_f)
                        total_sim_load += sim_load
                    total_peak += load_mw

                df_line.at[upstream_idx, 'sim_load'] = total_sim_load
                if total_peak > 0:
                     df_line.at[upstream_idx, 'sim_factor_cumulated'] = total_sim_load / total_peak
                else:
                     df_line.at[upstream_idx, 'sim_factor_cumulated'] = 0.0

        return df_line

    # Original analysis methods (kept for PLZ level aggregation)

    def analyse_basic_parameters_per_plz(self, plz: int):
        """Aggregate basic counts per transformer size across all grids of a PLZ."""
        cluster_list = self.dbc.get_list_from_plz(plz)
        count = len(cluster_list)
        time = 0
        percent = 0

        load_count_dict = {}
        bus_count_dict = {}
        cable_length_dict = {}
        trafo_dict = {}

        for kcid, bcid in cluster_list:
            try:
                net = self.dbc.read_net_db(plz, kcid, bcid)
            except Exception as e:
                self.dbc.logger.warning(f"Local network {kcid},{bcid} is problematic: {e}")
                continue

            load_count = len(net.load)
            bus_count = len(net.bus)
            cable_length = net.line["length_km"].sum()

            for row in net.trafo[["sn_mva"]].itertuples():
                capacity = round(row.sn_mva * 1e3)

                if capacity not in trafo_dict:
                    trafo_dict[capacity] = 0
                    load_count_dict[capacity] = []
                    bus_count_dict[capacity] = []
                    cable_length_dict[capacity] = []

                trafo_dict[capacity] += 1
                load_count_dict[capacity].append(load_count)
                bus_count_dict[capacity].append(bus_count)
                cable_length_dict[capacity].append(cable_length)

            time += 1
            if count > 0 and time / count >= 0.1:
                percent += 10
                self.dbc.logger.info(f"{percent} percent finished")
                time = 0

        self.dbc.insert_plz_parameters(
            plz,
            json.dumps(trafo_dict),
            json.dumps(load_count_dict),
            json.dumps(bus_count_dict)
        )

    def analyse_cables_per_plz(self, plz: int):
        """Sum cable lengths per standard type across all grids of a PLZ."""
        cluster_list = self.dbc.get_list_from_plz(plz)
        cable_length_dict = {}

        for kcid, bcid in cluster_list:
            try:
                net = self.dbc.read_net_db(plz, kcid, bcid)
            except Exception:
                continue

            cable_df = net.line[net.line["in_service"] == True]
            for std_type, group in cable_df.groupby("std_type"):
                length = (group["parallel"] * group["length_km"]).sum()
                cable_length_dict[std_type] = cable_length_dict.get(std_type, 0.0) + length

        self.dbc.insert_cable_length(plz, json.dumps(cable_length_dict))

    def analyse_trafo_parameters_per_plz(self, plz: int):
        """Collect per-transformer sim peak loads and distances for the PLZ.

        For each grid, compute:
        - sim_peak_load (kW) using category simultaneity factors
        - average and maximum LV-bus-to-load-bus distances (m) using topology weights
        Group by transformer size (kVA) and store lists per size for later lookup.
        """
        cluster_list = self.dbc.get_list_from_plz(plz)
        count = len(cluster_list)
        time = 0
        percent = 0

        trafo_load_dict = {}
        trafo_max_distance_dict = {}
        trafo_avg_distance_dict = {}

        for kcid, bcid in cluster_list:
            try:
                net = self.dbc.read_net_db(plz, kcid, bcid)
            except Exception as e:
                self.dbc.logger.warning(f"Local network {kcid},{bcid} is problematic: {e}")
                continue

            if net.trafo.empty:
                self.dbc.logger.warning(f"Grid {kcid},{bcid} has no transformer. Skipping in trafo analysis.")
                continue

            # Load buses
            load_bus = net.load["bus"].unique().tolist()
            if not load_bus:
                # No loads?
                continue

            # Calculate path distances from Transformer LV bus
            # Use pandapower topology
            # Ensure net has no switches open that shouldn't be (assuming default state is valid)
            lv_bus = net.trafo["lv_bus"].iloc[0]

            try:
                # Use pandapower's topology to get distances
                g = top.create_nxgraph(net, respect_switches=True)
                # distance to bus map (using line length as weight)
                dists = top.calc_distance_to_bus(net, lv_bus, weight="weight", respect_switches=True)
                # Filter for load buses
                trafo_distance_to_buses_km = dists.loc[load_bus].tolist()
            except Exception:
                # Topology error or unreachable
                continue

            # Load Aggregation per Category
            # Identify zones. If zone is missing, assume Residential?
            # Original code uses: ~net.bus["zone"].isin(["Commercial", "Public"])

            # Helper to get stats per category
            def get_cat_stats(mask):
                relevant_buses = net.bus[mask].index
                load_subset = net.load[net.load["bus"].isin(relevant_buses)]
                count = len(load_subset)
                sum_load_kw = load_subset["max_p_mw"].sum() * 1000.0
                return count, sum_load_kw

            res_mask = ~net.bus["zone"].isin(["Commercial", "Public"])
            com_mask = net.bus["zone"] == "Commercial"
            pub_mask = net.bus["zone"] == "Public"

            stats = {
                "Residential": get_cat_stats(res_mask),
                "Commercial": get_cat_stats(com_mask),
                "Public": get_cat_stats(pub_mask)
            }

            sim_peak_load = 0.0
            for cat, (count, sum_load) in stats.items():
                if count > 0:
                    sim_peak_load += utils.oneSimultaneousLoad(
                        installed_power=sum_load,
                        load_count=count,
                        sim_factor=SIM_FACTOR.get(cat, 1.0)
                    )

            # Convert distances to meters
            if trafo_distance_to_buses_km:
                avg_distance_m = (sum(trafo_distance_to_buses_km) / len(trafo_distance_to_buses_km)) * 1000.0
                max_distance_m = max(trafo_distance_to_buses_km) * 1000.0
            else:
                avg_distance_m = 0.0
                max_distance_m = 0.0

            trafo_size_kva = round(net.trafo["sn_mva"].iloc[0] * 1000.0)

            if trafo_size_kva not in trafo_load_dict:
                trafo_load_dict[trafo_size_kva] = []
                trafo_max_distance_dict[trafo_size_kva] = []
                trafo_avg_distance_dict[trafo_size_kva] = []

            trafo_load_dict[trafo_size_kva].append(sim_peak_load)
            trafo_max_distance_dict[trafo_size_kva].append(max_distance_m)
            trafo_avg_distance_dict[trafo_size_kva].append(avg_distance_m)

            time += 1
            if count > 0 and time / count >= 0.1:
                percent += 10
                self.dbc.logger.info(f"{percent} % processed")
                time = 0

        self.dbc.logger.info("analyse_per_trafo_parameters finished.")

        self.dbc.insert_trafo_parameters(
            plz,
            json.dumps(trafo_load_dict),
            json.dumps(trafo_max_distance_dict),
            json.dumps(trafo_avg_distance_dict)
        )
