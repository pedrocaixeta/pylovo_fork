import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore
import pandapower as pp
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans
from concurrent.futures import ProcessPoolExecutor, as_completed  # lightweight parallel execution

import src.database.database_client as dbc
from src.infdb.infdb_client import InfdbClient
from src.parameter_calculator import ParameterCalculator
from src import utils
from src.config_loader import *

# Import electrical backend components
from src.electrical_backend.backend_interface import IElectricalBackend
from src.electrical_backend import create_backend
from src.cable_installer import CableInstaller

class ResultExistsError(Exception):
    "Raised when the PLZ has already been created."
    pass


class GridGenerator:
    """
    Generates the grid for the given plz area
    """

    def __init__(self, plz=999999, **kwargs):
        self.plz = plz
        self.dbc = dbc.DatabaseClient()
        self.dbc.insert_version_if_not_exists()
        self.logger = utils.create_logger(
            name="GridGenerator", log_file=kwargs.get("log_file", "log.txt"), log_level=LOG_LEVEL
        )
        self.inf_dbc = None
        if USE_INFDB:
            self.inf_dbc = InfdbClient()

    def __del__(self):
        self.dbc.__del__()

    def generate_grid_for_single_plz(
        self, plz: int, analyze_grids: bool = False, refresh_mv: bool = True
    ) -> None:
        """Generates the grid for a single PLZ.

        :param plz: Postal code for which the grid should be generated.
        :type plz: int
        :param analyze_grids: Option to analyze the results after grid generation, defaults to False.
        :type analyze_grids: bool
        :param refresh_mv: Refresh materialized views after processing, defaults to True.
        :type refresh_mv: bool
        """
        self.plz = plz
        print('-------------------- start', self.plz, '---------------------------')
        self.dbc.create_temp_tables(plz)  # create PLZ-suffixed temp tables
        self.dbc.commit_changes() # only activate for debugging - otherwise multiprocessing does not work

        try:
            self.generate_grid()
            self.dbc.save_tables(plz=self.plz)  # Save data from temporary tables to result tables
            self.dbc.commit_changes()
            if analyze_grids:
                pc = ParameterCalculator()
                pc.calc_parameters_per_plz(plz=self.plz)
                self.dbc.commit_changes()  # commit the changes to the database
        except ResultExistsError:
            self.dbc.logger.info(f"Grid for the postcode area {plz} has already been generated.")
        except Exception as e:
            self.logger.error(f"Error during grid generation for PLZ {self.plz}: {e}")
            self.logger.info(f"Skipped PLZ {self.plz} due to generation error.")
            self.dbc.conn.rollback()  # rollback the transaction
            self.dbc.delete_plz_from_sample_set_table(str(CLASSIFICATION_VERSION), self.plz)  # delete from sample set
            traceback.print_exc()
        finally:
            # Always clean up temporary tables, even if there was an error
            self.dbc.drop_temp_tables(plz)  # drop PLZ-suffixed temp tables

        if refresh_mv:
            # update the materialized views to reflect changes in their base tables
            self.dbc.refresh_materialized_views()
        self.dbc.commit_changes()  # commit the changes to the database
        print('-------------------- end', self.plz, '-----------------------------')

    def generate_grid_for_multiple_plz(
        self, df_plz: pd.DataFrame, analyze_grids: bool = False, parallel: bool = True
    ) -> None:
        """Generate grids for all PLZ entries. Materialized views are refreshed once all grids have been processed.
        :param df_plz: table that contains PLZ for grid generation
        :param analyze_grids: option to analyse the results after grid generation, defaults to False
        :param parallel: optionally use parallel workers, defaults to True
        """
        plz_list = [int(row["plz"]) for _, row in df_plz.iterrows()]
        
        # Use parallel processing if:
        # 1. parallel=True AND
        # 2. We have multiple PLZ to process AND  
        # 3. We have more than 1 CPU core available (can't parallelize with 1 core)
        should_use_parallel = parallel and len(plz_list) > 1 and N_JOBS > 1
        
        print(f"🔍 Parallel processing check:")
        print(f"   - parallel parameter: {parallel}")
        print(f"   - Number of PLZ to process: {len(plz_list)}")
        print(f"   - Available CPU cores: {N_JOBS}")
        print(f"   - Will use parallel processing: {should_use_parallel}")
        
        if should_use_parallel:
            # Use parallel processing for multiple PLZ
            # Use up to N_JOBS workers, but not more than the number of PLZ
            max_workers = min(N_JOBS, len(plz_list))
            print(f"   - Using {max_workers} workers for {len(plz_list)} PLZ")
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # Create a dictionary that maps futures to their corresponding PLZ.
                futures = {
                    executor.submit(GridGenerator._worker, plz, analyze_grids): plz
                    for plz in plz_list
                }
                
                completed_count = 0
                total_count = len(plz_list)
                
                try:
                    worker_timeout_minutes = CONFIG_GENERATION.get("WORKER_TIMEOUT_MINUTES", 30)
                    worker_timeout = worker_timeout_minutes * 60  # Convert to seconds
                    for future in as_completed(futures, timeout=worker_timeout):
                        plz = futures[future]
                        completed_count += 1
                        
                        try:
                            # Calling future.result() will raise an exception if the worker process failed.
                            future.result()
                            print(f"✓ Completed PLZ {plz} ({completed_count}/{total_count})")
                        except Exception as exc:
                            # Log the exception to record the failed PLZ without stopping the execution
                            # for other, potentially successful, PLZs.
                            self.logger.error(f"PLZ {plz} generated an exception: {exc}")
                            traceback.print_exc()
                            print(f"✗ Failed PLZ {plz} ({completed_count}/{total_count})")
                            
                            # Clean up the failed future to prevent memory leaks
                            try:
                                future.cancel()
                            except Exception:
                                pass
                            
                except KeyboardInterrupt:
                    print(f"\n⚠️  KeyboardInterrupt received. Shutting down gracefully...")
                    print(f"   Completed: {completed_count}/{total_count} PLZ")
                    
                    # Cancel all pending futures
                    for future in futures:
                        future.cancel()
                    
                    # Wait a bit for ongoing processes to finish gracefully
                    print("   Waiting for ongoing processes to finish...")
                    try:
                        # Give processes time to finish gracefully based on config
                        shutdown_timeout = CONFIG_GENERATION.get("GRACEFUL_SHUTDOWN_TIMEOUT", 5)
                        for future in as_completed(futures, timeout=shutdown_timeout):
                            if not future.cancelled():
                                plz = futures[future]
                                try:
                                    future.result()
                                    print(f"✓ Gracefully completed PLZ {plz}")
                                except Exception as exc:
                                    print(f"✗ PLZ {plz} failed during graceful shutdown: {exc}")
                    except Exception:
                        # Timeout or other exception during graceful shutdown
                        pass
                    
                    print("   Shutdown complete.")
                    raise KeyboardInterrupt("Grid generation interrupted by user")
                    
                except Exception as e:
                    print(f"\n❌ Error during parallel processing: {e}")
                    print(f"   Completed: {completed_count}/{total_count} PLZ")
                    
                    # Cancel all pending futures on any error
                    for future in futures:
                        future.cancel()
                    
                    raise
        else:
            for plz in plz_list:
                # defer materialized view refresh until all PLZ are processed
                self.generate_grid_for_single_plz(
                    plz=plz, analyze_grids=analyze_grids, refresh_mv=False
                )

        # refresh materialized views once after all grids have been generated
        try:
            self.dbc.refresh_materialized_views()
            self.dbc.commit_changes()
        except Exception as e:
            self.logger.error(f"Error refreshing materialized views: {e}")
            # Don't re-raise here as individual PLZ processing might have succeeded

    @staticmethod
    def _worker(plz: int, analyze_grids: bool) -> None:
        """Worker process to generate a grid for a single PLZ."""
        log_file = Path("log") / f"log_{plz}.txt"
        if log_file.exists():
            log_file.unlink()  # Overwrite log file if it exists
        
        # Create a dedicated GridGenerator instance for this worker
        # This ensures each worker has its own database connection and logger
        gg = None
        try:
            print(f"Worker starting for PLZ {plz}...")
            gg = GridGenerator(log_file=log_file)  # dedicated logger per PLZ
            print(f"Worker initialized for PLZ {plz}")
            
            # Generate grid with proper error handling
            gg.generate_grid_for_single_plz(
                plz=plz, analyze_grids=analyze_grids, refresh_mv=False
            )
            
            print(f"Worker completed for PLZ {plz}")
            
        except Exception as e:
            print(f"Worker failed for PLZ {plz}: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure proper cleanup even on failure
            if gg and hasattr(gg, 'dbc') and gg.dbc:
                try:
                    gg.dbc.conn.rollback()
                except Exception as rollback_error:
                    print(f"Rollback error for PLZ {plz}: {rollback_error}")
            raise
        finally:
            # Ensure proper cleanup of database connections
            if gg and hasattr(gg, 'dbc') and gg.dbc:
                try:
                    # Use the close method which handles all connection types
                    gg.dbc.close()
                except Exception as cleanup_error:
                    print(f"Cleanup error for PLZ {plz}: {cleanup_error}")
            
            # Also ensure GridGenerator cleanup
            if gg:
                try:
                    gg.__del__()
                except Exception as del_error:
                    print(f"GridGenerator cleanup error for PLZ {plz}: {del_error}")
            
            print(f"Worker cleanup completed for PLZ {plz}")

    def generate_grid(self):
        if self.dbc.is_grid_generated(self.plz):
            raise ResultExistsError(
                f"The grids for the postcode area {self.plz} is already generated "
                f"for the version {VERSION_ID}."
            )
        self.prepare_data_from_config()
        self.prepare_postcodes()
        self.prepare_buildings()
        self.prepare_transformers()
        self.prepare_ways()
        self.apply_kmeans_clustering()
        self.position_all_transformers()
        self.install_cables()

    def prepare_data_from_config(self):
        """
        Load data from config.
        """
        self.dbc.insert_equipment_data_from_config(equipment_data=EQUIPMENT_DATA)
        self.dbc.commit_changes() # only activate for debugging - otherwise multiprocessing does not work
        self.dbc.insert_consumer_categories_from_config(consumer_categories=CONSUMER_CATEGORIES)

    def prepare_postcodes(self):
        """
        Caches postcode from raw data tables and stores in temporary tables.
        FROM: postcode
        INTO: postcode_result
        """
        self.dbc.copy_postcode_result_table(self.plz)
        self.logger.info(f"Working on plz {self.plz}")

    def prepare_buildings(self):
        """
        Caches buildings from raw data tables and stores in temporary tables.
        FROM: res, oth
        INTO: buildings_tem
        """
        if USE_INFDB:
            # Always pass the original plz to infdb client, let it handle testing_plz lookup internally
            buildings_data = self.inf_dbc.fetch_buildings_from_infdb(self.plz)
            self.dbc.set_buildings_table(buildings_data, self.plz)
        else:
            self.dbc.set_residential_buildings_table(self.plz)
            self.dbc.set_other_buildings_table(self.plz)
        # self.dbc.commit_changes() # only activate for debugging - otherwise multiprocessing does not work
        self.logger.info("Buildings_tem table prepared")
        self.dbc.remove_duplicate_buildings()
        self.logger.info("Duplicate buildings removed from buildings_tem")

        try:
            avg_hh = self.dbc.calculate_avg_households_per_building(self.plz)
            house_dist = self.dbc.calculate_house_distance_metric(self.plz)
            settlement_type = self.dbc.set_settlement_type_per_plz(self.plz, settlement_type_thresholds=
            {"rural_max_households": RURAL_MAX_HOUSEHOLDS,
             "urban_min_households": URBAN_MIN_HOUSEHOLDS,
             "rural_min_distance": RURAL_MIN_BUILDING_DISTANCE,
             "urban_max_distance": URBAN_MAX_BUILDING_DISTANCE})
            self.logger.info(
                f"Settlement type determined (avg_households_per_building={avg_hh:.2f}, house_distance={house_dist:.1f} m, settlement_type={settlement_type})"
            )
        except Exception as e:
            self.logger.warning(f"Settlement type classification failed: {e}")

        unloadcount = self.dbc.set_building_peak_load()
        self.logger.info(
            f"Building peakload calculated in buildings_tem, {unloadcount} unloaded buildings are removed from "
            f"buildings_tem"
        )
        too_large_consumers = self.dbc.update_too_large_consumers_to_zero()
        self.logger.debug(f"{too_large_consumers} too large consumers removed from buildings_tem")

        self.dbc.assign_close_buildings()
        self.logger.debug("All close buildings assigned and removed from buildings_tem")

    def prepare_transformers(self):
        """
        Cache transformers from raw data tables and stores in temporary tables.
        FROM: transformers
        INTO: buildings_tem
        """
        self.dbc.insert_transformers(self.plz)
        self.logger.info("Transformers inserted into buildings_tem table")
        self.dbc.count_indoor_transformers()
        self.dbc.drop_indoor_transformers()
        self.logger.info("Indoor transformers removed from buildings_tem table")

    def prepare_ways(self):
        """
        Cache ways, create network, connect buildings to the ways network
        FROM: ways, buildings_tem
        INTO: ways_tem, buildings_tem, ways_tem_vertices_pgr, ways_tem_
        """
        if USE_INFDB:
            # Always pass the original plz to infdb client, let it handle testing_plz lookup internally
            ways_rows = self.inf_dbc.fetch_ways_from_infdb(self.plz)
            ways_count = self.dbc.set_ways_tem_table_infdb(ways_rows, self.plz)
        else:
            ways_count = self.dbc.set_ways_tem_table(self.plz)
        self.logger.info(f"The ways_tem table filled with {ways_count} ways")

        # Run preprocessing functions that segment roads and connect buildings
        self.dbc.preprocess_ways()
        self.logger.info(f"Ways preprocessing completed in ways_tem.")

        # Build pgRouting topology on the processed network
        self.dbc.build_pgr_network_topology(self.plz)
        self.logger.info(f"pgRouting network topology created from ways_tem.")

        self.dbc.update_ways_cost()
        unconn = self.dbc.set_vertice_id()
        self.logger.debug(f"vertice id set, {unconn} buildings with no vertice id")

    def apply_kmeans_clustering(self):
        """
        Find connected components (subgraphs) of an undirected street graph using Depth-First Search algorithm over
        edges and vertices from ways_tem and, if necessary due to their size, apply k-means clustering to these
        street network components.

        FROM: ways_tem, buildings_tem
        INTO: ways_tem, vertices_pgr, buildings_tem
        """

        # Get connected components from the street network
        component, vertices = self.dbc.get_connected_component()
        component_ids = np.unique(component)

        if len(component_ids) > 0:
            # Handle components based on number
            if len(component_ids) > 1:
                # Process multiple connected components
                for i, component_id in enumerate(component_ids):
                    related_vertices = vertices[np.argwhere(component == component_id)]
                    self._process_component_to_kcid(related_vertices, i)
            else:
                # Process single connected component
                self._process_component_to_kcid(vertices)
        else:
            # No components found - issue warning
            warnings.warn("No connected components found in ways_tem table")

        # Verify clustering was successful for all buildings
        no_kmean_count = self.dbc.count_no_kmean_buildings()
        if no_kmean_count not in [0, None]:
            warnings.warn(f"K-means clustering issue: {no_kmean_count} buildings not assigned to clusters")

    def _process_component_to_kcid(self, vertices, component_index=None):
        """Helper method to process components to kcid groups"""
        conn_building_count = self.dbc.count_connected_buildings(vertices)

        if conn_building_count <= 1 or conn_building_count is None:
            # Remove isolated or empty components
            self.dbc.delete_ways(vertices)
            self.dbc.delete_transformers_from_buildings_tem(vertices)
            self.logger.debug("Empty/isolated component removed. Ways and transformers deleted from temporary tables.")
        elif conn_building_count >= LARGE_COMPONENT_LOWER_BOUND:
            # K-means applied to large component to define subgroups with cluster ids
            cluster_count = int(conn_building_count / LARGE_COMPONENT_DIVIDER)
            k_means = KMeans(n_clusters=cluster_count, random_state=K_MEANS_SEED, n_init="auto")
            (selected_vertices, coordinates) = self.dbc.get_connected_component_geometries(vertices)
            kcids = k_means.fit_predict(coordinates) + self.dbc.get_kcid_length() + 1
            self.dbc.update_kmeans_cluster_multiple(selected_vertices, kcids)
            log_msg = f"Large component {component_index} clustered into {cluster_count} groups" if component_index is not None else f"Large component clustered into {cluster_count} groups"
            self.logger.debug(log_msg)
        else:
            # Allocate cluster id for connected component smaller than the building threshold
            self.dbc.update_kmeans_cluster(vertices)

    def position_all_transformers(self):
        """
        Positions all transformers for each bcid cluster (brownfield with existing transformers and greenfield)
        FROM: buildings_tem, grid_result
        INTO: buildings_tem, grid_result
        """
        kcid_length = self.dbc.get_kcid_length()

        for _ in range(kcid_length):
            kcid = self.dbc.get_next_unfinished_kcid(self.plz)
            self.logger.debug(f"working on kcid {kcid}")
            # Building clustering
            # 0. Check for existing transformers from OSM
            transformers = self.dbc.get_included_transformers(kcid)

            # Case 1: No transformers present
            if not transformers:
                self.logger.debug(f"kcid{kcid} has no included transformer")
                # Create greenfield building clusters
                self.create_bcid_for_kcid(self.plz, kcid)
                self.logger.debug(f"kcid{kcid} building clusters finished")

            # Case 2: Transformers present
            else:
                self.logger.debug(f"kcid{kcid} has {len(transformers)} transformers")
                # Create brownfield building clusters with existing transformers
                self.position_brownfield_transformers(self.plz, kcid, transformers)

                # Check buildings and manage clusters
                if self.dbc.count_kmean_cluster_consumers(kcid) > 1:
                    self.create_bcid_for_kcid(self.plz, kcid) #TODO: name should include transformer_size allocation
                else:
                    self.dbc.delete_isolated_building(self.plz, kcid) #TODO: check approach with isolated buildings
                self.logger.debug("Remaining building clustering finished")

            # Process unfinished clusters
            for bcid in self.dbc.get_greenfield_bcids(self.plz, kcid):
                # Transformer positioning for greenfield clusters
                if bcid >= 0:
                    self.position_greenfield_transformers(self.plz, kcid, bcid)
                    self.logger.debug(f"Transformer positioning for kcid{kcid}, bcid{bcid} finished")
                    self.dbc.update_transformer_rated_power(self.plz, kcid, bcid, 1)
                    self.logger.debug("Transformer_rated_power in grid_result updated.")

    def create_bcid_for_kcid(self, plz: int, kcid: int) -> None:
        """
        Create building clusters (bcids) with average linkage method for a given kcid.
        :param plz: Postal code
        :param kcid: K-means cluster ID
        :return: None
        """
        # Get data needed for clustering
        buildings = self.dbc.get_buildings_from_kcid(kcid)
        consumer_cat_df = self.dbc.get_consumer_categories()
        settlement_type = self.dbc.get_settlement_type_from_plz(plz)
        transformer_capacities, _ = self.dbc.get_transformer_data(settlement_type)
        # Use the two largest available transformers
        double_trans = np.multiply(transformer_capacities[-2:], 2)

        # Get distance matrix and prepare for hierarchical clustering
        localid2vid, dist_mat, vid2localid = self.dbc.get_distance_matrix_from_kcid(kcid)
        dist_vector = squareform(dist_mat)

        if len(dist_vector) == 0:
            return

        # Initialize hierarchical clustering
        Z = linkage(dist_vector, method="average")
        valid_cluster_dict = {}
        invalid_trans_cluster_dict = {}
        cluster_amount = 2
        new_localid2vid = localid2vid

        # Iterative clustering process
        while True:
            # Try clustering with current parameters
            invalid_cluster_dict, cluster_dict, _ = self.dbc.try_clustering(Z, cluster_amount, new_localid2vid, buildings,
                                                                        consumer_cat_df, transformer_capacities,
                                                                        double_trans)

            # Process valid clusters
            if cluster_dict:
                current_valid_amount = len(valid_cluster_dict)
                valid_cluster_dict.update({x + current_valid_amount: y for x, y in cluster_dict.items()})
                valid_cluster_dict = dict(enumerate(valid_cluster_dict.values()))  # reindexing the dict with enumerate

            # Process invalid clusters
            if invalid_cluster_dict:
                current_invalid_amount = len(invalid_trans_cluster_dict)
                invalid_trans_cluster_dict.update(
                    {x + current_invalid_amount: y for x, y in invalid_cluster_dict.items()})
                invalid_trans_cluster_dict = dict(enumerate(invalid_trans_cluster_dict.values()))

            # Check if clustering is complete
            if not invalid_trans_cluster_dict:
                self.logger.info(
                    f"Found {len(valid_cluster_dict)} single transformer clusters for KCID: {kcid} (postcode: {plz})")
                break
            else:
                # Process too large clusters by re-clustering them
                self.logger.info(
                    f"Found {len(invalid_trans_cluster_dict)} too_large clusters for PLZ: {plz}, KCID: {kcid}")

                # Get buildings from the first too-large cluster for re-clustering
                invalid_vertice_ids = list(invalid_trans_cluster_dict[0])
                invalid_local_ids = [vid2localid[v] for v in invalid_vertice_ids]

                # Create new mappings and distance matrix for the subclustering
                new_localid2vid = {k: v for k, v in localid2vid.items() if k in invalid_local_ids}
                new_localid2vid = dict(enumerate(new_localid2vid.values()))
                new_dist_mat = dist_mat[invalid_local_ids][:, invalid_local_ids]
                new_dist_vector = squareform(new_dist_mat)

                # Prepare for next iteration
                Z = linkage(new_dist_vector, method="average")
                cluster_amount = 2
                del invalid_trans_cluster_dict[0]
                invalid_trans_cluster_dict = dict(enumerate(invalid_trans_cluster_dict.values()))

        # At this point, a valid clustering solution (minimum number of transformers) was found.
        # Each cluster:
        #   1. Contains buildings that can be supplied by a single transformer
        #   2. Has an appropriately sized transformer assigned
        # The valid_cluster_dict maps building cluster IDs to tuples of (building_vertices_list, optimal_transformer_size)
        # We could calculate the total transformer cost by summing the costs of all selected transformers:
        # total_transformer_cost = sum([transformer2cost[v[1]] for v in valid_cluster_dict.values()])

        # Reorder bcids for consistency
        valid_cluster_dict = self._order_clusters_by_min_vertice(valid_cluster_dict)

        # Save results to database
        self.dbc.clear_grid_result_in_kmean_cluster(plz, kcid)
        for bcid, cluster_data in valid_cluster_dict.items():
            self.dbc.upsert_bcid(plz, kcid, bcid, vertices=cluster_data[0],
                                         transformer_rated_power=cluster_data[1])
        self.logger.debug(f"bcids for plz {plz} kcid {kcid} created.")

        self.logger.debug(f"bcids for plz {plz} kcid {kcid} found...")

    def _order_clusters_by_min_vertice(self, cluster_dict: dict) -> dict:
        """
        Helper to reassign bcids based on smallest vertex ID of each cluster
        for consistent ordering across equivalent partitions.
        Helper function to reassign bcids of the given building clusters ordered by the smallest vertice IDs of the clusters.
        Returns the same result for cluster distributions that are equivalent up to renaming.
        :param cluster_dict: input clusters
        :return: reordered clusters
        """
        ordered_vertices = sorted(cluster_dict.items(), key = lambda cluster: min(cluster[1][0]))
        return {new_bcid: vertices for new_bcid, (_, vertices) in enumerate(ordered_vertices, start=1)}

    def position_brownfield_transformers(self, plz: int, kcid: int, transformer_list: list) -> None:
        """
        Assign buildings to the existing transformers and store them as bcid in buildings_tem.
        Args:
            plz: Postal code
            kcid: K-means cluster ID
            transformer_list: List of transformer IDs
        """
        self.logger.info(f"{len(transformer_list)} transformers found for {kcid}")

        # Get cost dataframe between consumers and transformers
        cost_df = self.dbc.get_consumer_to_transformer_df(kcid, transformer_list)

        # Filter out connections with distance >= 800
        cost_df = cost_df[cost_df["agg_cost"] < MAX_BROWNFIELD_TRAFO_DISTANCE].sort_values(by=["agg_cost"])

        # Initialize tracking variables
        pre_result_dict = {transformer_id: [] for transformer_id in transformer_list}
        full_transformer_list = []
        assigned_consumer_list = []

        # Assign consumers to closest transformer
        for _, row in cost_df.iterrows():
            start_consumer_id = row["start_vid"]
            end_transformer_id = row["end_vid"]

            # Skip if consumer already assigned or transformer full
            if start_consumer_id in assigned_consumer_list or end_transformer_id in full_transformer_list:
                continue

            # Try to assign consumer to transformer
            pre_result_dict[end_transformer_id].append(int(start_consumer_id))
            sim_load = self.dbc.calculate_sim_load(pre_result_dict[end_transformer_id])

            # Check if transformer capacity exceeded
            if float(sim_load) >= 630:
                # Remove consumer and mark transformer as full
                pre_result_dict[end_transformer_id].pop()
                full_transformer_list.append(end_transformer_id)

                # Exit if all transformers are full
                if len(full_transformer_list) == len(transformer_list):
                    self.logger.debug("All transformers full")
                    break
            else:
                # Mark consumer as assigned
                assigned_consumer_list.append(start_consumer_id)

        self.logger.info("Transformer selection finished")

        # Create building clusters for each transformer
        building_cluster_count = 0
        for transformer_id in transformer_list:
            # Skip empty transformers
            if not pre_result_dict[transformer_id]:
                self.logger.debug(f"Transformer {transformer_id} has no assigned consumer, deleted")
                self.dbc.delete_transformers_from_buildings_tem([transformer_id])
                continue

            # Create building cluster with sequential negative ID
            building_cluster_count -= 1

            # Calculate the simulated load for all loads assigned to this transformer
            sim_load = self.dbc.calculate_sim_load(pre_result_dict[transformer_id])

            # Define the available standard transformer sizes in kVA
            possible_transformers = np.array([100, 160, 250, 400, 630])  # TODO: check with settlement_type approach

            # Select the smallest transformer that is larger than the simulated load
            transformer_rated_power = possible_transformers[possible_transformers > float(sim_load)][0].item()

            # Update database with new building cluster
            self.dbc.update_building_cluster(transformer_id, pre_result_dict[transformer_id], building_cluster_count, kcid,
                plz, transformer_rated_power)

        self.logger.info("Brownfield clusters completed")


    def position_greenfield_transformers(self, plz, kcid, bcid):
        """
        Positions a transformer at the optimal location for a greenfield building cluster.

        The optimal location minimizes the sum of distance*load from each vertex to others.

        Args:
            plz: Postcode
            kcid: Kmeans cluster ID
            bcid: Building cluster ID
        """
        # Get all connection points in the building cluster
        connection_points = self.dbc.get_building_connection_points_from_bc(kcid, bcid)

        # If there's only one connection point, use it
        if len(connection_points) == 1:
            self.dbc.upsert_transformer_selection(plz, kcid, bcid, connection_points[0])
            return

        # Get distance matrix between all connection points
        localid2vid, dist_mat, _ = self.dbc.get_distance_matrix_from_bcid(kcid, bcid)

        # Get load vector for each connection point
        loads = self.dbc.generate_load_vector(kcid, bcid)

        # Calculate weighted distance (distance * load) for each potential location
        total_load_per_vertice = dist_mat.dot(loads)

        # Select the point with minimum weighted distance as transformer location
        min_localid = np.argmin(total_load_per_vertice)
        ont_connection_id = int(localid2vid[min_localid])

        # Update the database with the selected transformer position
        self.dbc.upsert_transformer_selection(plz, kcid, bcid, ont_connection_id)

        self.logger.info("Greenfield clusters completed")

    def prepare_vertices_list(self, plz: int, kcid: int, bcid: int) -> tuple[
        dict, int, list, pd.DataFrame, pd.DataFrame, list, list]:
        vertices_dict, ont_vertice = self.dbc.get_vertices_from_bcid(plz, kcid, bcid)
        vertices_list = list(vertices_dict.keys())

        buildings_df = self.dbc.get_buildings_from_bcid(plz, kcid, bcid)
        consumer_df = self.dbc.get_consumer_categories()
        consumer_list = buildings_df.vertice_id.to_list()
        consumer_list = list(dict.fromkeys(consumer_list))  # removing duplicates

        connection_nodes = [i for i in vertices_list if i not in consumer_list]

        return (vertices_dict, ont_vertice, vertices_list, buildings_df, consumer_df, consumer_list, connection_nodes,)

    def get_consumer_simultaneous_load_dict(self, consumer_list: list, buildings_df: pd.DataFrame) -> tuple[
        dict, dict, dict]:
        Pd = {consumer: 0 for consumer in consumer_list}  # dict of all vertices in bc, 0 as default
        load_units = {consumer: 0 for consumer in consumer_list}
        load_type = {consumer: "SFH" for consumer in consumer_list}

        for row in buildings_df.itertuples():
            load_units[row.vertice_id] = row.households_per_building
            load_type[row.vertice_id] = row.type
            gzf = CONSUMER_CATEGORIES.loc[CONSUMER_CATEGORIES.definition == row.type, "sim_factor"].item()

            # Determine simultaneous load of each building in MW
            Pd[row.vertice_id] = utils.oneSimultaneousLoad(row.peak_load_in_kw * 1e-3, row.households_per_building, gzf)

        return Pd, load_units, load_type

    def install_cables(self):
        """
        Installs electrical cables using the electrical backend pattern.

        The algorithm works as follows:
        1. Retrieves all clusters (kcid, bcid) for the postal code area
        2. For each cluster:
           a. Prepares building and connection data
           b. Creates an electrical network via backend
           c. Adds buses, transformers, and loads using ComponentSpecs
           d. Installs cables using the same branch-by-branch greedy algorithm
        3. Tracks progress and saves the network configurations

        Returns:
            None
        """
        # Get all clusters for the postal code area
        cluster_list = self.dbc.get_list_from_plz(self.plz)
        if TESTING:
            cluster_list = cluster_list[:5]  # Limit to first 5 clusters for testing
        ci_count = 0
        ci_process = 0

        for id in cluster_list:
            kcid, bcid = id
            self.logger.info(f"Start cable installation for PLZ {self.plz} kcid {kcid} bcid {bcid}")

            # Get data for this cluster
            vertices_dict, ont_vertice, vertices_list, buildings_df, consumer_df, consumer_list, connection_nodes = (
                self.prepare_vertices_list(self.plz, kcid, bcid)
            )
            Pd, load_units, load_type = self.get_consumer_simultaneous_load_dict(consumer_list, buildings_df)

            # Initialize backend using configuration
            backend = create_backend(ELECTRICAL_BACKEND, logger=self.logger)
            circuit_name = f"PLZ{self.plz}_kcid{kcid}_bcid{bcid}"
            backend.initialize_circuit(name=circuit_name, source_bus="MVbus 1", primary_kv=20.0)

            # Register cable types from equipment data
            backend.register_cable_types(self.dbc.fetch_cables())

            # Get all available cable types for main distribution
            all_available_cables = list(backend.net.std_types["line"].keys())
            local_length_dict = {c: 0 for c in all_available_cables}

            # Create cable installer
            installer = CableInstaller(backend, self.dbc, self.logger)
            
            # Create network components
            installer.create_lvmv_bus(self.plz, kcid, bcid)
            installer.create_transformer(self.plz, kcid, bcid)
            installer.create_connection_bus(connection_nodes)
            installer.create_consumer_bus_and_load(consumer_list, load_units, load_type, buildings_df, CONSUMER_CATEGORIES)

            self.logger.info(
                f"Backend network initialized (buses={len(backend.net.bus)}, loads={len(backend.net.load)}, "
                f"transformer_rated_power={self.dbc.get_transformer_rated_power_from_bcid(self.plz, kcid, bcid)} kVA)"
            )

            # Install cables branch by branch (same logic as original)
            branch_deviation = 0
            connection_node_list = connection_nodes
            branch_index = 0

            while connection_node_list:
                # Handle single remaining node case
                if len(connection_node_list) == 1:
                    remaining = connection_node_list[0]
                    self.logger.debug(
                        f"Final remaining connection node {remaining} (kcid={kcid}, bcid={bcid}); installing direct connection."
                    )
                    sim_load = utils.simultaneousPeakLoad(buildings_df, consumer_df, connection_node_list)
                    Imax = sim_load / (VN * V_BAND_LOW * np.sqrt(3))

                    # Install consumer cables
                    local_length_dict = installer.install_consumer_cables(
                        self.plz, bcid, kcid, branch_deviation, connection_node_list,
                        ont_vertice, vertices_dict, Pd, CONSUMER_CONNECTION_AVAILABLE_CABLES, local_length_dict,
                    )

                    # Connect to transformer
                    if connection_node_list[0] == ont_vertice:
                        cable, count = installer.find_minimal_available_cable(Imax)
                        installer.create_line_ont_to_lv_bus(
                            self.plz, bcid, kcid, connection_node_list[0], branch_deviation, cable, count
                        )
                    else:
                        cable, count = installer.find_minimal_available_cable(
                            Imax, vertices_dict[connection_nodes[0]]
                        )
                        length = installer.create_line_start_to_lv_bus(
                            self.plz, bcid, kcid, connection_node_list[0], branch_deviation,
                            vertices_dict, cable, count, ont_vertice
                        )
                        local_length_dict[cable] += length
                        self.logger.info(
                            f"Final branch backbone installed (PLZ={self.plz}, kcid={kcid}, bcid={bcid}, "
                            f"start_node={connection_node_list[0]}, cable={cable}, parallels={count}, length_km={length:.4f})"
                        )
                    break

                furthest_node_path_list = self.find_furthest_node_path_list(
                    connection_node_list, vertices_dict, ont_vertice
                )
                branch_node_list, Imax = self.determine_maximum_load_branch(
                    furthest_node_path_list, buildings_df, consumer_df
                )
                self.logger.debug(
                    f"Selected branch {branch_index} (nodes={len(branch_node_list)}, first={branch_node_list[0]}, "
                    f"last={branch_node_list[-1]}, Imax={Imax:.3f} kA)"
                )

                # Install cables for this branch
                local_length_dict = installer.install_consumer_cables(
                    self.plz, bcid, kcid, branch_deviation, branch_node_list,
                    ont_vertice, vertices_dict, Pd, CONSUMER_CONNECTION_AVAILABLE_CABLES, local_length_dict
                )

                # Select appropriate cable and connect nodes
                branch_distance = vertices_dict[branch_node_list[0]]
                cable, count = installer.find_minimal_available_cable(
                    Imax, branch_distance
                )

                if len(branch_node_list) >= 2:
                    local_length_dict = installer.create_line_node_to_node(
                        self.plz, kcid, bcid, branch_node_list, branch_deviation,
                        vertices_dict, local_length_dict, cable, ont_vertice, count
                    )

                # Connect branch to transformer
                branch_start_node = branch_node_list[-1]
                if branch_start_node == ont_vertice:
                    installer.create_line_ont_to_lv_bus(
                        self.plz, bcid, kcid, branch_start_node, branch_deviation, cable, count
                    )
                    self.logger.debug(
                        f"Branch {branch_index} connected directly to transformer (cable={cable}, parallels={count})."
                    )
                else:
                    length = installer.create_line_start_to_lv_bus(
                        self.plz, bcid, kcid, branch_start_node, branch_deviation,
                        vertices_dict, cable, count, ont_vertice
                    )
                    local_length_dict[cable] += length
                    self.logger.debug(
                        f"Branch {branch_index} connected to LV bus (cable={cable}, parallels={count}, length_km={length:.4f})."
                    )

                # Update processed nodes and visualization
                for vertice in branch_node_list:
                    connection_node_list.remove(vertice)

                installer.deviate_bus_geodata(branch_node_list, branch_deviation)
                branch_deviation += 1
                branch_index += 1

            # Cluster summary
            total_length = sum(local_length_dict.values())
            used_cables = {k: v for k, v in local_length_dict.items() if v > 0}
            if used_cables:
                cable_summary = ", ".join([f"{k}:{v:.3f} km" for k, v in sorted(used_cables.items(), key=lambda x: -x[1])])
            else:
                cable_summary = "no cables installed"
            self.logger.info(
                f"Finished cluster kcid={kcid}, bcid={bcid}: branches={branch_index}, lines={len(backend.net.line)}, "
                f"total_length={total_length:.3f} km ({cable_summary})"
            )

            # Track and report progress
            ci_count += 1
            progress_increment = 10  # Report progress in 10% increments
            progress_threshold = max(1, len(cluster_list) / progress_increment)

            if ci_count >= progress_threshold:
                ci_process += progress_increment
                ci_count = 0
                self.logger.info(
                    f"Cable installation: {min(ci_process, 100)}% complete ({ci_process // progress_increment}/{progress_increment})"
                )

            self.save_net(backend, kcid, bcid)

    def save_net(self, backend: IElectricalBackend, kcid, bcid):
        """
        Save grid to file and database using backend pattern.
        """
        if SAVE_GRID_FOLDER:
            savepath_folder = Path(RESULT_DIR, "grids", f"version_{VERSION_ID}", str(self.plz))
            savepath_folder.mkdir(parents=True, exist_ok=True)
            filename = f"kcid{kcid}bcid{bcid}.json"
            savepath_file = Path(savepath_folder, filename)
            backend.export_to_format(filename=savepath_file)

        json_string = backend.export_to_format(filename=None)

        self.dbc.save_pp_net_with_json(self.plz, kcid, bcid, json_string)

        self.logger.info(f"Grid with kcid:{kcid} bcid:{bcid} is stored. ")

