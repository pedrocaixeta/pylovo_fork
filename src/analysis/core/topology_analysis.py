"""
Topology analysis helpers for low-voltage (LV) distribution grids built with pandapower.

This module computes descriptive parameters of radial LV grids that are used for
analysis, validation, and clustering. It relies on:
- pandapower for grid modeling
- networkx for graph/topology metrics with edge weights (e.g., cable lengths)
- geopandas and haversine distances for spatial proximity metrics between houses

Key concepts and assumptions:
- The LV grid is treated as a radial network rooted at the LV transformer bus ("LVbus").
- Loads (house connections) are represented as pandapower loads grouped per bus.
- "Branches" refer to the main feeders from the LV bus; they are approximated as the
  number of incident edges of the root bus minus the direct connection to the transformer.
- Simultaneity factors (SIM_FACTOR) are used to aggregate loads per category
  (Residential/Public/Commercial) when estimating coincident peak load along a feeder.

Outputs include counts (buses, loads), distances (avg/max path length from transformer),
lengths (cable length), transformer sizing, and simple impedance-weighted proxies that
correlate with voltage drop ("resistance"/"vsw" aggregates).

Note: Some heuristics assume unique upstream line per bus and a radial topology.
"""

import math
import json
import statistics
from math import radians
import pandas as pd
import geopandas as gpd
import networkx as nx
import pandapower as pp
from sklearn.metrics.pairwise import haversine_distances
import pandapower.topology as top

import src.database.database_client as dbc
from src.config_loader import *
from src import utils


class ParameterCalculator:
    """Class to calculate and persist grid parameters.

    The calculator orchestrates two scopes:
    1) PLZ level: aggregate statistics across all local grids inside a PLZ
       (basic counts, cable length per type, transformer-distance relationships).
    2) Grid level: detailed parameters per local grid (kcid, bcid) for clustering.

    Attributes
    - plz: Postcode area ID
    - bcid: Building cluster ID (negative bcid implies an OSM-only transformer)
    - kcid: K-means cluster ID of the grid
    - version_id: Analysis version taken from configuration
    - dbc: Database client used to read/write pandapower nets and parameters
    - lvbus_keyword: substring that identifies the LV root bus in bus names (default: "LVbus")
    - consumer_bus_keyword: substring that identifies consumer buses (default: "Consumer Nodebus")
    - connection_bus_keyword: substring that identifies internal connection buses (default: "Connection Nodebus")
    """

    def __init__(self, plz: int, bcid: int, kcid: int,
                 keyword_lvbus: str = "LVbus",
                 keyword_consumer_bus: str = "Consumer Nodebus",
                 keyword_connection_bus: str = "Connection Nodebus"):
        self.dbc = dbc.DatabaseClient()
        self.version_id = VERSION_ID
        self.plz = plz
        self.bcid = bcid
        self.kcid = kcid
        # Configurable keywords for bus identification across different datasets
        self.lvbus_keyword = keyword_lvbus
        self.consumer_bus_keyword = keyword_consumer_bus
        self.connection_bus_keyword = keyword_connection_bus

    def calc_parameters_per_plz(self):
        """Compute and store PLZ-wide parameters.

        Side effects
        - Reads all nets of the PLZ from the database.
        - Writes aggregated per-PLZ results and sets analysis flags.
        - Logs progress and skips already analyzed PLZs.
        """
        grid_generated = self.dbc.is_grid_generated(self.plz)
        if not grid_generated:
            self.dbc.logger.info(f"Grid for the postcode area {self.plz} is not generated, yet. Generate it first.")
            return
        grid_analysed = self.dbc.is_grid_analyzed(self.plz)
        if grid_analysed:
            self.dbc.logger.info(f"Grid for the postcode area {self.plz} has already been analyzed.")
            return

        try:
            self.dbc.logger.info("Start basic result analysis")
            self.analyse_basic_parameters_per_plz(self.plz)
            self.dbc.logger.info("Start cable counting")
            self.analyse_cables_per_plz(self.plz)
            self.dbc.logger.info("Start per trafo analysis")
            self.analyse_trafo_parameters_per_plz(self.plz)
            self.dbc.logger.info("Result analysis finished")
            self.dbc.conn.commit()
        except Exception as e:
            self.dbc.logger.error(f"Error during analysis for PLZ {self.plz}: {e}")
            self.dbc.logger.info(f"Skipped PLZ {self.plz} due to analysis error.")
            self.dbc.delete_plz_from_sample_set_table(str(CLASSIFICATION_VERSION), self.plz)  # delete from sample set

    def calc_parameters_per_grid(self):
        """Compute and store per-grid parameters for all grids of an already analyzed PLZ.

        Ensures PLZ-level metrics were computed first (for lookups such as
        simultaneous peak load by transformer size and distance).
        """
        grid_analysed = self.dbc.is_grid_analyzed(self.plz)
        if not grid_analysed:
            self.dbc.logger.info(
                f"PLZ parameters for the postcode area {self.plz} missing. Please run calc_parameters_per_plz() first.")
            return

        parameter_count = self.dbc.count_clustering_parameters(plz=self.plz)
        if parameter_count > 0:
            print(f"The parameters for the grids of postcode area {self.plz} and version {VERSION_ID} "
                  f"have already been calculated.")
            return

        cluster_list = self.dbc.get_list_from_plz(self.plz)
        for kcid, bcid in cluster_list:
            print(bcid, kcid)
            self.calc_grid_parameters(bcid, kcid)

    def calc_grid_parameters(self, bcid: int, kcid: int) -> None:
        """Compute parameters for a single local grid and persist them.

        Parameters
        - bcid: Building cluster ID
        - kcid: Grid cluster ID

        Writes a record to the clustering-parameters table including metadata
        (plz, bcid, kcid, version, osm_trafo flag).
        """
        self.bcid = bcid
        self.kcid = kcid
        osm_trafo = self.has_osm_trafo()

        net = self.dbc.read_net_db(self.plz, self.kcid, self.bcid)
        params = self.compute_parameters(net)
        params.update({"version_id": self.version_id, "plz": self.plz, "bcid": self.bcid, "kcid": self.kcid,
                       "osm_trafo": bool(osm_trafo)})

        self.dbc.insert_clustering_parameters(params)

    def compute_parameters(self, net: pp.pandapowerNet) -> dict:
        """Compute a consistent set of topology and load metrics for one grid.

        Metrics returned (units):
        - no_connection_buses (count): buses of type "Connection Nodebus"
        - no_branches (count): main feeders leaving the LV bus
        - no_house_connections (count): buses of type "Consumer Nodebus"
        - no_house_connections_per_branch (count/branch)
        - no_households (count): number of load elements
        - no_household_equ (HE): equivalent number of households from max power and PEAK_LOAD_HOUSEHOLD
        - no_households_per_branch (HE/branch)
        - max_no_of_households_of_a_branch (HE): max per-branch HE aggregated along the paths
        - house_distance_km (km): spatial median of mean distance to 4 nearest consumer buses
        - transformer_mva (MVA): transformer rating
        - max_trafo_dis (km), avg_trafo_dis (km): weighted path length from LV bus to consumer buses
        - cable_length_km (km), cable_len_per_house (km/house connection)
        - max_power_mw (MW): sum of max_p_mw of all loads
        - simultaneous_peak_load_mw (MW): from PLZ lookup by trafo size and max path distance
        - resistance (Ohm*HE, proxy): aggregated resistance-weighted load proxy along all consumer paths
        - reactance (Ohm*HE, proxy) and ratio (R/X)
        - vsw_per_branch (proxy/branch): resistance proxy per branch
        - max_vsw_of_a_branch (proxy): worst branch resistance proxy
        """
        no_house_connections = self.get_no_of_buses(net, self.consumer_bus_keyword)
        no_connection_buses = self.get_no_of_buses(net, self.connection_bus_keyword)
        no_households = self.get_no_households(net)
        max_power_mw = self.get_max_power(net)

        no_household_equ = max_power_mw * 1000.0 / PEAK_LOAD_HOUSEHOLD
        cable_length_km = self.get_cable_length(net)
        cable_len_per_house = cable_length_km / no_house_connections if no_house_connections > 0 else 0.0

        # CRITICAL FIX: respect_switches=True to analyze operational (radial) topology
        # This is essential for DSO networks that use open switches for radial operation
        G = pp.topology.create_nxgraph(net, respect_switches=True)
        no_branches = self.get_no_branches(G, net)
        avg_trafo_dis, max_trafo_dis = self.get_distances_in_graph(net, G)

        # Zero-division protection for branch metrics
        if no_branches > 0:
            no_house_connections_per_branch = no_house_connections / no_branches
            no_households_per_branch = max_power_mw * 1000.0 / (PEAK_LOAD_HOUSEHOLD * no_branches)
        else:
            no_house_connections_per_branch = 0.0
            no_households_per_branch = 0.0

        transformer_mva = self.get_trafo_power(net)
        house_distance_km = self.calc_avg_house_distance(net)
        simultaneous_peak_load_mw = self.get_simultaneous_peak_load(transformer_mva, max_trafo_dis)
        (max_no_of_households_of_a_branch, resistance, reactance, ratio,
         max_vsw_of_a_branch,) = self.calc_resistance(net, G)

        vsw_per_branch = resistance / no_branches if no_branches > 0 else 0.0

        return {"no_connection_buses": int(no_connection_buses),
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
                "reactance": float(reactance), "ratio": float(ratio),
                "vsw_per_branch": float(vsw_per_branch),
                "max_vsw_of_a_branch": float(max_vsw_of_a_branch)}

    def get_parameters_as_dataframe(self, net: pp.pandapowerNet) -> pd.DataFrame:
        """Return parameters as a one-row DataFrame with CLUSTERING_PARAMETERS columns."""
        params = self.compute_parameters(net)
        return pd.DataFrame([params], columns=CLUSTERING_PARAMETERS)

    def get_simultaneous_peak_load(self, transformer_mva: float, max_trafo_dis: float) -> float:
        """Lookup coincident peak load for a transformer size and max distance.

        The lookup uses precomputed per-PLZ dictionaries persisted in the database,
        keyed by transformer size (kVA as string) and discretized max distance (m).

        Parameters
        - transformer_mva: transformer rating in MVA
        - max_trafo_dis: maximum weighted path distance from LV bus to consumer bus in km

        Returns
        - simultaneous peak load in MW (0.0 if no exact match)
        """
        data_list, _, _ = self.dbc.read_per_trafo_dict(self.plz)
        transformer_type_str = str(int(transformer_mva * 1000))
        max_trafo_distance_list = data_list[3][transformer_type_str]
        if max_trafo_dis * 1000 in max_trafo_distance_list:
            sim_load_index = max_trafo_distance_list.index(max_trafo_dis * 1000)
            simultaneous_peak_load_mw = data_list[2][transformer_type_str][sim_load_index] / 1000
            return simultaneous_peak_load_mw
        return 0.0

    def has_osm_trafo(self) -> bool:
        """Return True if the grid's transformer originates from OSM data (bcid < 0)."""
        return self.bcid < 0

    def get_max_power(self, pandapower_net: pp.pandapowerNet) -> float:
        """Sum of installed maximum active power (MW) over all loads."""
        df_load = pandapower_net.load
        return df_load["max_p_mw"].sum()

    def get_no_households(self, pandapower_net: pp.pandapowerNet) -> int:
        """Number of load elements (proxy for number of households)."""
        df_load = pandapower_net.load
        return len(df_load["name"])

    def get_no_of_buses(self, pandapower_net: pp.pandapowerNet, bus_description: str) -> int:
        """Count buses whose name contains a given description (substring match)."""
        df_bus = pandapower_net.bus
        df_bus["type_bus"] = df_bus["name"].str.contains(bus_description)
        return df_bus["type_bus"].sum()

    def get_cable_length(self, pandapower_net: pp.pandapowerNet) -> float:
        """Total circuit length in km across all line elements."""
        df_line = pandapower_net.line
        return df_line["length_km"].sum()

    def calc_avg_house_distance(self, pandapower_net: pp.pandapowerNet) -> float:
        """Compute a spatial neighbor metric for consumer buses.

        For each consumer bus, compute the mean distance to its 4 nearest other
        consumer buses. Return the median of these per-bus averages for robustness.
        Returns 0.0 if fewer than 2 consumer buses.

        Automatically detects coordinate system:
        - Geographic (WGS84): uses haversine distance
        - Projected (e.g., EPSG:3035): uses Euclidean distance in meters
        """
        bus_geo = pandapower_net.bus_geodata.copy()

        if len(bus_geo) == 0:
            return 0.0

        bus_geo = gpd.GeoDataFrame(bus_geo, geometry=gpd.points_from_xy(bus_geo["x"], bus_geo["y"]))
        bus = pandapower_net.bus.copy()
        bus_geo = bus_geo.merge(bus, left_index=True, right_index=True)
        bus_geo["consumer_bus"] = bus_geo["name"].str.contains(self.consumer_bus_keyword)
        bus_geo = bus_geo[bus_geo["consumer_bus"]]

        if len(bus_geo) < 2:
            return 0.0

        # Detect coordinate system based on coordinate ranges
        x_vals = bus_geo["geometry"].x
        y_vals = bus_geo["geometry"].y
        is_geographic = (x_vals.min() >= -180 and x_vals.max() <= 180 and
                        y_vals.min() >= -90 and y_vals.max() <= 90)

        list_pt = []
        for pt in bus_geo["geometry"]:
            if is_geographic:
                # Geographic coordinates: convert to radians for haversine
                new_pt = [radians(pt.x), radians(pt.y)]
            else:
                # Projected coordinates: use as-is (in meters)
                new_pt = [pt.x, pt.y]
            list_pt.append(new_pt)

        if is_geographic:
            # Use haversine distance for geographic coordinates
            dis_mat = haversine_distances(list_pt, list_pt)
            dis_mat = dis_mat * 6371.0  # Convert to km (Earth radius)
        else:
            # Use Euclidean distance for projected coordinates
            from scipy.spatial.distance import cdist
            dis_mat = cdist(list_pt, list_pt, metric='euclidean')
            dis_mat = dis_mat / 1000.0  # Convert meters to km

        df_distances = pd.DataFrame(dis_mat)
        list_avg_dis4pts = []

        for column in df_distances:
            smallest = df_distances[column].nsmallest(5)
            avg = (smallest.sum() - smallest.iloc[0]) / 4 if len(smallest) > 1 else 0.0
            list_avg_dis4pts.append(avg)

        if not list_avg_dis4pts:
            return 0.0

        median_dis = statistics.median(list_avg_dis4pts)
        return median_dis

    def get_root(self, pandapower_net: pp.pandapowerNet):
        """Return the LV root bus index (first bus whose name contains the configured LV keyword).

        Raises
        - ValueError if no LV bus is found.
        """
        root = pandapower_net.bus
        root["LV_bus"] = root["name"].str.contains(self.lvbus_keyword)
        root = root[root["LV_bus"]]
        if root.empty:
            raise ValueError(f"No LV bus found using keyword '{self.lvbus_keyword}' for PLZ {self.plz}, "
                             f"kcid {self.kcid}, bcid {self.bcid}.")
        root = list(root.index)[0]
        return root

    def get_no_branches(self, networkx_graph: nx.Graph, pandapower_net: pp.pandapowerNet) -> int:
        """Approximate the number of main feeders from the LV bus.

        Computed as the degree of the LV root bus minus one (to ignore the HV/LV transformer link).
        Returns at least 0.
        """
        root = self.get_root(pandapower_net)
        # DegreeView supports indexing to get a concrete int degree for a node
        root_degree = networkx_graph.degree[root]
        return int(max(root_degree - 1, 0))

    def get_distances_in_graph(self, pandapower_net: pp.pandapowerNet, networkx_graph: nx.Graph) -> tuple[float, float]:
        """Calculate average and maximum weighted distances from the transformer to consumer buses.

        Uses Dijkstra shortest paths on the pandapower topology graph with 'weight'
        edge attribute (typically km). Returns (avg_km, max_km). If no consumers
        are present or no paths exist, returns (0.0, 0.0).
        """
        root = self.get_root(pandapower_net)
        leaves = pandapower_net.bus.copy()
        leaves["consumer_bus"] = leaves["name"].str.contains(self.consumer_bus_keyword)
        leaves = list(leaves[leaves["consumer_bus"]].index)

        if len(leaves) == 0:
            return 0.0, 0.0

        path_length_to_leaves = []
        for leaf in leaves:
            # Skip leaves not in the graph (can happen with filtered/multi-component graphs)
            if leaf not in networkx_graph:
                continue
            try:
                weighted_length = nx.dijkstra_path_length(networkx_graph, root, leaf, weight='weight')
                path_length_to_leaves.append(weighted_length)
            except nx.NetworkXNoPath:
                continue
            except nx.NodeNotFound:
                # Root or leaf not in graph
                continue

        if not path_length_to_leaves:
            return 0.0, 0.0

        max_path_length = max(path_length_to_leaves)
        avg_path_length = sum(path_length_to_leaves) / len(path_length_to_leaves)

        return avg_path_length, max_path_length

    def get_trafo_power(self, pandapower_net: pp.pandapowerNet) -> float:
        """Transformer rating in MVA (assumes exactly one LV transformer). Raises if missing."""
        df_trafo = pandapower_net.trafo.sn_mva
        if df_trafo.empty:
            raise ValueError(f"No transformer found for PLZ {self.plz}, kcid {self.kcid}, bcid {self.bcid}.")
        return df_trafo.iloc[0]

    def calc_resistance(self, pandapower_net: pp.pandapowerNet, networkx_graph: nx.Graph) -> tuple[
        float, float, float, float, float]:
        """Aggregate impedance-weighted proxies along consumer paths.

        For each consumer bus, determine its shortest path to the LV root. For each
        line segment along that path, compute an impedance-weighted contribution
        proportional to cable parameters and an estimate of simultaneous load on the
        segment. Sum across all consumers to obtain:
        - max_no_of_households_of_a_branch: max HE per branch (branch derived from the first
          edge leaving the root that belongs to the consumer's path)
        - resistance: sum over all consumer-path section resistances (Ohm*HE proxy)
        - reactance: analogous with x_ohm_per_km (Ohm*HE proxy)
        - ratio: R/X ratio (0 if X is 0)
        - max_vsw_of_a_branch: max per-branch resistance proxy (higher suggests worse voltage drop risk)
        """
        df_load = pandapower_net.load
        # Household equivalents (HE) per house-connection bus: MW to kW and divide by PEAK_LOAD_HOUSEHOLD
        df_vsw = df_load.groupby("bus")["max_p_mw"].sum() * 1000.0 / PEAK_LOAD_HOUSEHOLD
        df_vsw = df_vsw.to_frame().reset_index().rename(
            columns={"bus": "house_connection", "max_p_mw": "household_equivalents"})

        df_line = self.calculate_line_with_sim_factor(pandapower_net, networkx_graph)
        root = self.get_root(pandapower_net)

        # Shortest path from root to each house-connection bus
        df_vsw["path"] = ""
        for index, row in df_vsw.iterrows():
            house_conn = df_vsw.at[index, "house_connection"]
            # Skip if house connection or root not in graph (multi-component case)
            if house_conn not in networkx_graph or root not in networkx_graph:
                df_vsw.at[index, "path"] = []
                continue
            try:
                df_vsw.at[index, "path"] = nx.shortest_path(networkx_graph, source=root,
                                                            target=house_conn)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                self.dbc.logger.warning(
                    f"No path from LV root {root} to house_connection {house_conn} "
                    f"for PLZ {self.plz}, kcid {self.kcid}, bcid {self.bcid}. Skipping.")
                df_vsw.at[index, "path"] = []

        # Determine branch by the first edge that leaves the root present in the path
        df_vsw["branch"] = ""
        for branch in networkx_graph.edges(root):
            for index, row in df_vsw.iterrows():
                if branch[1] in row["path"]:
                    df_vsw.at[index, "branch"] = branch

        if len(df_vsw) > 0:
            grp = df_vsw.groupby("branch")["household_equivalents"].sum()
            max_no_of_households_of_a_branch = grp.max() if len(grp) > 0 else 0.0
        else:
            max_no_of_households_of_a_branch = 0.0

        # Accumulate section impedances weighted by HE and simultaneity factor per line
        df_vsw["resistance"] = ""
        df_vsw["resistance_sections"] = ""
        df_vsw["reactance"] = ""
        df_vsw["reactance_sections"] = ""
        for index, row in df_vsw.iterrows():
            path_list = df_vsw.at[index, "path"]
            length = len(path_list)
            no_load = df_vsw.at[index, "household_equivalents"]
            resistance_list = []
            reactance_list = []
            for i in range(length - 1):
                start_node = path_list[i]
                end_node = path_list[i + 1]
                # match either orientation
                line = df_line[(df_line["from_bus"] == start_node) & (df_line["to_bus"] == end_node)]
                if line.empty:
                    line = df_line[(df_line["from_bus"] == end_node) & (df_line["to_bus"] == start_node)]
                if line.empty:
                    raise ValueError(
                        f"No line segment found for path edge {start_node}->{end_node} in grid (PLZ {self.plz}, "
                        f"kcid {self.kcid}, bcid {self.bcid}). This indicates a malformed or non-radial net.")
                line = line.head(1)
                # Cable section parameters (per km); apply simultaneity factor to resistance proxy
                length_km = line["length_km"].iloc[0]
                r_ohm_per_km = line["r_ohm_per_km"].iloc[0]
                x_ohm_per_km = line["x_ohm_per_km"].iloc[0]
                sim_factor = line["sim_factor_cumulated"].iloc[0]
                resistance_of_cable_section = no_load * length_km * r_ohm_per_km * sim_factor
                resistance_list.append(resistance_of_cable_section)
                reactance_of_cable_section = no_load * length_km * x_ohm_per_km
                reactance_list.append(reactance_of_cable_section)
            df_vsw.at[index, "resistance"] = math.fsum(resistance_list)
            df_vsw.at[index, "resistance_sections"] = resistance_list
            df_vsw.at[index, "reactance"] = math.fsum(reactance_list)
            df_vsw.at[index, "reactance_sections"] = reactance_list

        resistance = df_vsw["resistance"].sum()
        reactance = df_vsw["reactance"].sum()
        ratio = resistance / reactance if reactance > 0 else 0.0
        max_vsw_of_a_branch = df_vsw.groupby("branch")["resistance"].sum().max()

        return max_no_of_households_of_a_branch, resistance, reactance, ratio, max_vsw_of_a_branch

    def calculate_line_with_sim_factor(self, pandapower_net, networkx_graph) -> pd.DataFrame:
        """Annotate each line segment with simultaneity and load aggregation metadata.

        Returns a copy of pandapower's line table augmented with:
        - sim_factor_cumulated: equivalent simultaneity factor at the upstream end of the line
        - sim_load: coincident load (MW) aggregated from the downstream subtree
        - number and installed power per category (commercial/public/residential)

        Algorithm outline
        1) Level-1 (leaf/consumer buses): For each consumer bus and load zone, compute
           load counts and sums; derive per-bus simultaneity using SIM_FACTOR and
           utils.oneSimultaneousLoad(). Write results into the upstream line whose to_bus
           equals the consumer bus.
        2) Connection buses (internal aggregation points): process from furthest to
           nearest to the transformer, summing downstream category counts and loads and
           recomputing sim_factor_cumulated and sim_load at the upstream line.

        Assumptions
        - Radial topology with a unique upstream line for a given bus.
        - The actual LV root bus index is derived and used for path-length sorting.
        """
        df_sim_factor_definitions = pd.DataFrame.from_dict(SIM_FACTOR, orient='index')
        df_sim_factor_definitions.reset_index(inplace=True)
        df_sim_factor_definitions.columns = ['description', 'sim_factor']

        # The idea is to add to each line new attributes needed to calculate the
        # simultaneity factor for each line (cable segment). The simultaneity factor
        # is needed to calculate the vsw-like resistance proxies.

        net_line_with_sim_factor = pandapower_net.line
        net_line_with_sim_factor['sim_factor_cumulated'] = 0.0
        net_line_with_sim_factor['sim_load'] = 0.0
        net_line_with_sim_factor['no_commercial'] = 0
        net_line_with_sim_factor['load_commercial_mw'] = 0.0
        net_line_with_sim_factor['no_public'] = 0
        net_line_with_sim_factor['load_public_mw'] = 0.0
        net_line_with_sim_factor['no_residential'] = 0
        net_line_with_sim_factor['load_residential_mw'] = 0.0
        net_line_with_sim_factor.drop(['c_nf_per_km', 'g_us_per_km', 'max_i_ka', 'df', 'type', 'in_service'], axis=1,
                                      inplace=True)
        net_line_with_sim_factor = net_line_with_sim_factor.drop_duplicates()

        # First, calculate the simultaneity factor for the consumer buses

        level1 = pd.merge(left=pandapower_net.load, left_on='bus', right=pandapower_net.bus,
                          right_on=pandapower_net.bus.index)
        # Map residential building subtypes to a single "Residential" category
        level1.replace(['MFH', 'SFH', 'AB', 'TH'], 'Residential', inplace=True)

        load_value = level1.groupby(['bus', 'zone'])['max_p_mw'].sum()
        load_value = pd.DataFrame(load_value)
        load_value = load_value.reset_index()

        load_count = level1.groupby(['bus', 'zone'])['name_x'].count()
        load_count = pd.DataFrame(load_count)
        load_count = load_count.reset_index()
        load_count = load_count.rename(columns={'name_x': 'count'})

        load_count = pd.merge(left=load_count, left_on='bus', right=load_value, right_on='bus')
        load_count.drop(['zone_y'], axis=1, inplace=True)

        load_count_cat = pd.merge(left=load_count, left_on='zone_x', right=df_sim_factor_definitions,
                                  right_on='description')

        load_count_cat = load_count_cat.assign(
            sim_factor_level1=lambda x: utils.oneSimultaneousLoad(installed_power=1, load_count=x['count'],
                                                            sim_factor=x['sim_factor']))

        load_count_cat = load_count_cat.assign(sim_load_level1=lambda x: x['max_p_mw'] * x['sim_factor_level1'])

        # Enter these values into the upstream line that ends at the consumer bus (to_bus)
        for index, row in load_count_cat.iterrows():
            bus = row['bus']
            # find the unique incident line regardless of orientation
            idx_to = net_line_with_sim_factor.index[net_line_with_sim_factor['to_bus'] == bus].tolist()
            idx_fr = net_line_with_sim_factor.index[net_line_with_sim_factor['from_bus'] == bus].tolist()
            idx = (idx_to + idx_fr)
            if len(idx) == 0:
                self.dbc.logger.warning(
                    f"No upstream line (incident to bus={bus}) found to annotate simultaneity for PLZ {self.plz}, "
                    f"kcid {self.kcid}, bcid {self.bcid}. Skipping bus.")
                continue
            target_index = idx[0]
            net_line_with_sim_factor.at[target_index, 'sim_factor_cumulated'] = row['sim_factor_level1']
            net_line_with_sim_factor.at[target_index, 'sim_load'] = row['sim_load_level1']
            if row['description'] == 'Commercial':
                net_line_with_sim_factor.at[target_index, 'no_commercial'] = row['count']
                net_line_with_sim_factor.at[target_index, 'load_commercial_mw'] = row['max_p_mw']
                net_line_with_sim_factor.at[target_index, 'no_public'] = 0
                net_line_with_sim_factor.at[target_index, 'load_public_mw'] = 0
                net_line_with_sim_factor.at[target_index, 'no_residential'] = 0
                net_line_with_sim_factor.at[target_index, 'load_residential_mw'] = 0
            elif row['description'] == 'Public':
                net_line_with_sim_factor.at[target_index, 'no_commercial'] = 0
                net_line_with_sim_factor.at[target_index, 'load_commercial_mw'] = 0
                net_line_with_sim_factor.at[target_index, 'no_public'] = row['count']
                net_line_with_sim_factor.at[target_index, 'load_public_mw'] = row['max_p_mw']
                net_line_with_sim_factor.at[target_index, 'no_residential'] = 0
                net_line_with_sim_factor.at[target_index, 'load_residential_mw'] = 0
            elif row['description'] == 'Residential':
                net_line_with_sim_factor.at[target_index, 'no_commercial'] = 0
                net_line_with_sim_factor.at[target_index, 'load_commercial_mw'] = 0
                net_line_with_sim_factor.at[target_index, 'no_public'] = 0
                net_line_with_sim_factor.at[target_index, 'load_public_mw'] = 0
                net_line_with_sim_factor.at[target_index, 'no_residential'] = row['count']
                net_line_with_sim_factor.at[target_index, 'load_residential_mw'] = row['max_p_mw']

        # Work on the connection nodebuses and their aggregated simultaneity factors

        connection_bus = pandapower_net.bus
        connection_bus['connection_bus'] = connection_bus['name'].str.contains(self.connection_bus_keyword)
        connection_bus = connection_bus[connection_bus['connection_bus']]
        connection_bus = connection_bus.index
        connection_bus = list(connection_bus)

        # Sort connection buses by graph distance to the transformer (furthest first)
        df_connection_bus = pd.DataFrame(connection_bus, columns=['bus'])
        root_bus = self.get_root(pandapower_net)
        df_connection_bus['source'] = root_bus  # use real LV root bus index

        len_path_list = []
        for index, row in df_connection_bus.iterrows():
            bus = row['bus']
            # Skip if bus not in graph (multi-component case)
            if bus not in networkx_graph or root_bus not in networkx_graph:
                len_path_list.append(0)
                continue
            try:
                length = nx.shortest_path_length(networkx_graph, source=row['source'], target=bus)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                self.dbc.logger.warning(
                    f"No path from LV root {root_bus} to connection bus {bus} for PLZ {self.plz}, "
                    f"kcid {self.kcid}, bcid {self.bcid}. Skipping bus in ordering.")
                length = 0
            len_path_list.append(length)
        df_connection_bus['len_to_trafo_in_graph'] = len_path_list
        df_connection_bus = df_connection_bus.sort_values(by=['len_to_trafo_in_graph'], ascending=False)

        # Propagate aggregated counts and simultaneity upstream (towards the transformer)
        for index, row in df_connection_bus.iterrows():
            furthest_connection_bus = row['bus']
            connected_downstream = net_line_with_sim_factor[
                net_line_with_sim_factor['from_bus'] == furthest_connection_bus]
            # Upstream: towards the trafo
            connected_upstream = net_line_with_sim_factor[net_line_with_sim_factor['to_bus'] == furthest_connection_bus]
            upstream_index = connected_upstream.index
            if len(upstream_index) == 0:
                # try from_bus orientation
                connected_upstream = net_line_with_sim_factor[net_line_with_sim_factor['from_bus'] == furthest_connection_bus]
                upstream_index = connected_upstream.index
                if len(upstream_index) == 0:
                    self.dbc.logger.warning(
                        f"No upstream line (incident to bus={furthest_connection_bus}) to record aggregated loads for PLZ {self.plz}, "
                        f"kcid {self.kcid}, bcid {self.bcid}. Skipping.")
                    continue
            net_line_with_sim_factor.at[upstream_index[0], 'no_commercial'] = connected_downstream[
                'no_commercial'].sum()
            net_line_with_sim_factor.at[upstream_index[0], 'load_commercial_mw'] = connected_downstream[
                'load_commercial_mw'].sum()
            net_line_with_sim_factor.at[upstream_index[0], 'no_public'] = connected_downstream['no_public'].sum()
            net_line_with_sim_factor.at[upstream_index[0], 'load_public_mw'] = connected_downstream[
                'load_public_mw'].sum()
            net_line_with_sim_factor.at[upstream_index[0], 'no_residential'] = connected_downstream[
                'no_residential'].sum()
            net_line_with_sim_factor.at[upstream_index[0], 'load_residential_mw'] = connected_downstream[
                'load_residential_mw'].sum()

            # Recompute coincident loads per category using category simultaneity factors
            load_commercial = utils.oneSimultaneousLoad(
                installed_power=net_line_with_sim_factor.at[upstream_index[0], 'load_commercial_mw'],
                load_count=net_line_with_sim_factor.at[upstream_index[0], 'no_commercial'],
                sim_factor=SIM_FACTOR['Commercial'])

            load_public = utils.oneSimultaneousLoad(
                installed_power=net_line_with_sim_factor.at[upstream_index[0], 'load_public_mw'],
                load_count=net_line_with_sim_factor.at[upstream_index[0], 'no_public'], sim_factor=SIM_FACTOR['Public'])

            load_residential = utils.oneSimultaneousLoad(
                installed_power=net_line_with_sim_factor.at[upstream_index[0], 'load_residential_mw'],
                load_count=net_line_with_sim_factor.at[upstream_index[0], 'no_residential'],
                sim_factor=SIM_FACTOR['Residential'])

            net_line_with_sim_factor.at[
                upstream_index[0], 'sim_load'] = load_commercial + load_public + load_residential

            peak_load_all_consumer_types = net_line_with_sim_factor.at[upstream_index[0], 'load_commercial_mw'] + \
                                           net_line_with_sim_factor.at[upstream_index[0], 'load_public_mw'] + \
                                           net_line_with_sim_factor.at[upstream_index[0], 'load_residential_mw']
            if peak_load_all_consumer_types == 0:
                net_line_with_sim_factor.at[
                    upstream_index[0], 'sim_factor_cumulated'] = 0  # print('Connection nodebus error')
            else:
                net_line_with_sim_factor.at[upstream_index[0], 'sim_factor_cumulated'] = (
                            net_line_with_sim_factor.at[upstream_index[0], 'sim_load'] / peak_load_all_consumer_types)

        return net_line_with_sim_factor

    def analyse_basic_parameters_per_plz(self, plz: int):
        """Aggregate basic counts per transformer size across all grids of a PLZ.

        For each local grid, count loads and unique load buses, compute cable length, and
        group them by transformer size (kVA). Persists json-encoded dictionaries for later
        lookup and reporting.
        """
        cluster_list = self.dbc.get_list_from_plz(plz)
        count = len(cluster_list)
        time = 0
        percent = 0

        load_count_dict = {}
        bus_count_dict = {}
        cable_length_dict = {}
        trafo_dict = {}
        self.dbc.logger.debug("start basic parameter counting")
        for kcid, bcid in cluster_list:
            load_count = 0
            bus_list = []
            try:
                net = self.dbc.read_net_db(plz, kcid, bcid)
            except Exception as e:
                self.dbc.logger.warning(f" local network {kcid},{bcid} is problematic")
                raise e
            else:
                for row in net.load[["name", "bus"]].itertuples():
                    load_count += 1
                    bus_list.append(row.bus)
                bus_list = list(set(bus_list))
                bus_count = len(bus_list)
                cable_length = net.line["length_km"].sum()

                for row in net.trafo[["sn_mva", "lv_bus"]].itertuples():
                    capacity = round(row.sn_mva * 1e3)

                    if capacity in trafo_dict:
                        trafo_dict[capacity] += 1

                        load_count_dict[capacity].append(load_count)
                        bus_count_dict[capacity].append(bus_count)
                        cable_length_dict[capacity].append(cable_length)

                    else:
                        trafo_dict[capacity] = 1

                        load_count_dict[capacity] = [load_count]
                        bus_count_dict[capacity] = [bus_count]
                        cable_length_dict[capacity] = [cable_length]

            time += 1
            if time / count >= 0.1:
                percent += 10
                self.dbc.logger.info(f"{percent} percent finished")
                time = 0
        self.dbc.logger.info("analyse_basic_parameters finished.")
        trafo_string = json.dumps(trafo_dict)
        load_count_string = json.dumps(load_count_dict)
        bus_count_string = json.dumps(bus_count_dict)

        self.dbc.insert_plz_parameters(plz, trafo_string, load_count_string, bus_count_string)

    def analyse_cables_per_plz(self, plz: int):
        """Sum cable lengths per standard type across all grids of a PLZ and persist result."""
        cluster_list = self.dbc.get_list_from_plz(plz)
        count = len(cluster_list)
        time = 0
        percent = 0

        # distributed according to cross_section
        cable_length_dict = {}
        for kcid, bcid in cluster_list:
            try:
                net = self.dbc.read_net_db(plz, kcid, bcid)
            except Exception as e:
                self.dbc.logger.debug(f" local network {kcid},{bcid} is problematic")
                raise e
            else:
                cable_df = net.line[net.line["in_service"] == True]

                cable_type = pd.unique(cable_df["std_type"]).tolist()
                for type in cable_type:

                    if type in cable_length_dict:
                        cable_length_dict[type] += (cable_df[cable_df["std_type"] == type]["parallel"] *
                                                    cable_df[cable_df["std_type"] == type]["length_km"]).sum()

                    else:
                        cable_length_dict[type] = (cable_df[cable_df["std_type"] == type]["parallel"] *
                                                   cable_df[cable_df["std_type"] == type]["length_km"]).sum()
            time += 1
            if time / count >= 0.1:
                percent += 10
                self.dbc.logger.info(f"{percent} % processed")
                time = 0
        self.dbc.logger.info("analyse_cables finished.")
        cable_length_string = json.dumps(cable_length_dict)
        self.dbc.insert_cable_length(plz, cable_length_string)

    def analyse_trafo_parameters_per_plz(self, plz: int):
        """Collect per-transformer simultaneous peak loads and distances across the PLZ.

        For each local grid, compute:
        - sim_peak_load (kW) using category simultaneity factors
        - average and maximum LV-bus-to-load-bus distances (m) using topology weights
        Group results by transformer size (kVA) and store lists per size for later lookup.
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
                self.dbc.logger.warning(f" local network {kcid},{bcid} is problematic")
                raise e
            else:
                if net.trafo.empty:
                    self.dbc.logger.warning(f"Grid {kcid},{bcid} has no transformer. Skipping in trafo analysis.")
                    continue
                trafo_sizes = net.trafo["sn_mva"].tolist()[0]

                load_bus = pd.unique(net.load["bus"]).tolist()

                # CRITICAL FIX: respect_switches=True for operational topology
                top.create_nxgraph(net, respect_switches=True)
                trafo_distance_to_buses = (
                    top.calc_distance_to_bus(net, net.trafo["lv_bus"].tolist()[0], weight="weight",
                                             respect_switches=True, ).loc[load_bus].tolist())

                # calculate total sim_peak_load
                residential_bus_index = net.bus[~net.bus["zone"].isin(["Commercial", "Public"])].index.tolist()
                commercial_bus_index = net.bus[net.bus["zone"] == "Commercial"].index.tolist()
                public_bus_index = net.bus[net.bus["zone"] == "Public"].index.tolist()

                residential_house_num = net.load[net.load["bus"].isin(residential_bus_index)].shape[0]
                public_house_num = net.load[net.load["bus"].isin(public_bus_index)].shape[0]
                commercial_house_num = net.load[net.load["bus"].isin(commercial_bus_index)].shape[0]

                residential_sum_load = (net.load[net.load["bus"].isin(residential_bus_index)]["max_p_mw"].sum() * 1e3)
                public_sum_load = (net.load[net.load["bus"].isin(public_bus_index)]["max_p_mw"].sum() * 1e3)
                commercial_sum_load = (net.load[net.load["bus"].isin(commercial_bus_index)]["max_p_mw"].sum() * 1e3)

                sim_peak_load = 0
                for building_type, sum_load, house_num in zip(["Residential", "Public", "Commercial"],
                                                               [residential_sum_load, public_sum_load,
                                                                commercial_sum_load],
                                                               [residential_house_num, public_house_num,
                                                                commercial_house_num], ):
                    if house_num:
                        sim_peak_load += utils.oneSimultaneousLoad(installed_power=sum_load, load_count=house_num,
                                                                   sim_factor=SIM_FACTOR[building_type], )

                # Distances returned by pandapower are in km; convert to meters for stored statistics
                avg_distance = (sum(trafo_distance_to_buses) / len(trafo_distance_to_buses)) * 1e3
                max_distance = max(trafo_distance_to_buses) * 1e3

                trafo_size = round(trafo_sizes * 1e3)

                if trafo_size in trafo_load_dict:
                    trafo_load_dict[trafo_size].append(sim_peak_load)

                    trafo_max_distance_dict[trafo_size].append(max_distance)

                    trafo_avg_distance_dict[trafo_size].append(avg_distance)

                else:
                    trafo_load_dict[trafo_size] = [sim_peak_load]
                    trafo_max_distance_dict[trafo_size] = [max_distance]
                    trafo_avg_distance_dict[trafo_size] = [avg_distance]

            time += 1
            if time / count >= 0.1:
                percent += 10
                self.dbc.logger.info(f"{percent} % processed")
                time = 0
        self.dbc.logger.info("analyse_per_trafo_parameters finished.")

        trafo_load_string = json.dumps(trafo_load_dict)
        trafo_max_distance_string = json.dumps(trafo_max_distance_dict)
        trafo_avg_distance_string = json.dumps(trafo_avg_distance_dict)
        self.dbc.insert_trafo_parameters(plz, trafo_load_string, trafo_max_distance_string, trafo_avg_distance_string)
