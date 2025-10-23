"""
Grid splitter for DSO networks containing multiple LV grids.

This module provides functionality to split a pandapower network containing
multiple LV grids into individual grid networks for separate analysis.

Supports both:
- Naming convention-based splitting (SWD, Forchheim formats)
- Generic topology-based splitting (for any network structure)
"""

import pandapower as pp
import pandapower.topology as top
from typing import List, Dict, Any, Optional
import logging
import pandas as pd
import os


class GridSplitter:
    """
    Class to split multi-grid networks into individual grids.

    Automatically detects the appropriate splitting method based on
    the network structure and naming conventions.
    """

    def __init__(
        self,
        net: pp.pandapowerNet,
        method: str = 'auto',
        lv_index: int = 7,
        trafo_index: int = 6
    ):
        """
        Initialize the grid splitter.

        Parameters
        ----------
        net : pp.pandapowerNet
            Network containing multiple LV grids
        method : str
            Splitting method: 'auto', 'naming', 'topology'
        lv_index : int
            Index for LV buses in naming convention (default: 7)
        trafo_index : int
            Index for transformers in naming convention (default: 6)
        """
        self.net = net
        self.method = method
        self.lv_index = lv_index
        self.trafo_index = trafo_index
        self.logger = logging.getLogger(__name__)

    def split(self) -> List[pp.pandapowerNet]:
        """
        Split the network into individual grids.

        Returns
        -------
        list of pp.pandapowerNet
            List of individual grid networks, one per transformer
        """
        return split_multi_grid_network(
            self.net,
            use_naming_convention=(self.method != 'topology'),
            lv_index=self.lv_index,
            trafo_index=self.trafo_index
        )

    def save_grids(
        self,
        grids: List[pp.pandapowerNet],
        output_dir: str,
        prefix: str = "grid",
        save_json: bool = True,
        save_excel: bool = False,
        save_info_csv: bool = True
    ) -> pd.DataFrame:
        """
        Save split grids to files.

        Parameters
        ----------
        grids : list of pp.pandapowerNet
            Grids to save
        output_dir : str
            Output directory
        prefix : str
            Filename prefix
        save_json : bool
            Save JSON files
        save_excel : bool
            Save Excel files
        save_info_csv : bool
            Save summary CSV

        Returns
        -------
        pd.DataFrame
            Summary information
        """
        return save_split_grids(
            grids,
            output_dir=output_dir,
            prefix=prefix,
            save_json=save_json,
            save_excel=save_excel,
            save_info_csv=save_info_csv
        )


# Convenience function
def split_network(net: pp.pandapowerNet, **kwargs) -> List[pp.pandapowerNet]:
    """
    Convenience function to split a multi-grid network.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network to split
    **kwargs
        Arguments passed to GridSplitter

    Returns
    -------
    list of pp.pandapowerNet
        Individual grids
    """
    splitter = GridSplitter(net, **kwargs)
    return splitter.split()


# Original standalone functions preserved below


def split_multi_grid_network(
    net: pp.pandapowerNet,
    use_naming_convention: bool = True,
    lv_index: int = 7,
    trafo_index: int = 6
) -> List[pp.pandapowerNet]:
    """
    Split a pandapower network containing multiple LV grids into separate networks.

    This is necessary for DSO data that contains multiple independent LV grids
    in a single JSON file. Each grid is identified by its transformer.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network containing multiple LV grids
    use_naming_convention : bool
        If True, tries to use SWF naming convention (bus names like 7XXX for LV)
        If False or naming convention not found, uses topology-based approach
    lv_index : int
        Index for LV buses in naming convention (default: 7)
    trafo_index : int
        Index for transformers in naming convention (default: 6)

    Returns
    -------
    list of pp.pandapowerNet
        List of individual grid networks, one per transformer
    """
    logger = logging.getLogger(__name__)

    if net.trafo.empty:
        logger.warning("Network has no transformers, returning as single grid")
        return [net]

    num_trafos = len(net.trafo)
    logger.info(f"Network contains {num_trafos} transformers - splitting into individual grids...")

    # Try naming convention approach first (SWF-specific)
    if use_naming_convention and _has_naming_convention(net, lv_index):
        logger.info("Using naming convention approach (SWF format detected)")
        return _split_by_naming_convention(net, lv_index, trafo_index)

    # Fall back to topology-based approach
    logger.info("Using topology-based approach")
    return _split_by_topology(net)


def _has_naming_convention(net: pp.pandapowerNet, lv_index: int) -> bool:
    """
    Check if network uses SWF naming convention.

    Returns True if bus names follow pattern like 7XXX (where X are digits).
    """
    # Check if 'chr_name' column exists (SWF networks use this)
    if 'chr_name' not in net.bus.columns:
        return False

    # Check if there are buses starting with the lv_index
    lv_buses = net.bus[net.bus["chr_name"].astype(str).str.startswith(str(lv_index))]

    # Need at least some LV buses to use this approach
    return len(lv_buses) > 0


def _split_by_naming_convention(
    net: pp.pandapowerNet,
    lv_index: int = 7,
    trafo_index: int = 6
) -> List[pp.pandapowerNet]:
    """
    Split network using naming convention.

    Supports two patterns:
    1. SWF: Transformers named "6XXX", buses "7XXX" where XXX is grid code
    2. SWD: Transformers named "MSNS_TrSt_XXXX", LV buses "7XXXYYY..." where XXX is grid code
    """
    logger = logging.getLogger(__name__)

    # Check if transformers follow pattern "6XXX" (SWF) or need alternative approach (SWD)
    trafo_has_grid_codes = net.trafo["name"].astype(str).str.startswith(str(trafo_index)).any()

    if trafo_has_grid_codes:
        # SWF pattern: use transformer names to identify grids
        logger.info("Detected SWF pattern (transformers with 6XXX naming)")
        return _split_by_naming_swf(net, lv_index, trafo_index)
    else:
        # SWD pattern: use LV bus names connected to transformers
        logger.info("Detected SWD pattern (using LV bus names from transformers)")
        return _split_by_naming_swd(net, lv_index)


def _split_by_naming_swf(
    net: pp.pandapowerNet,
    lv_index: int = 7,
    trafo_index: int = 6
) -> List[pp.pandapowerNet]:
    """
    Split network using SWF naming convention (original swf_subnets logic).
    """
    logger = logging.getLogger(__name__)

    # Find all unique grid identifiers from bus names
    grid_codes = sorted(
        net.bus.loc[
            net.bus["chr_name"].astype(str).str.startswith(str(lv_index)),
            "chr_name"
        ].astype(str).str[1:4].unique(),
        key=int
    )

    logger.info(f"Found {len(grid_codes)} potential grids from bus names")

    grids = []

    for grid_code in grid_codes:
        try:
            # Get all LV buses for this grid
            lv_buses = list(
                net.bus[net.bus["chr_name"].astype(str).str.contains(f"{lv_index}{grid_code}")].index
            )

            if not lv_buses:
                continue

            # Find transformers for this grid
            trafos = net.trafo[net.trafo["name"].astype(str).str.contains(f"{trafo_index}{grid_code}")]

            if trafos.empty:
                continue

            # Add HV buses of transformers to the subnet
            subbuses = lv_buses.copy()
            subbuses.extend(list(net.bus.loc[trafos["hv_bus"]].index))

            # Extract subnet
            subnet = pp.select_subnet(net, buses=subbuses, keep_everything_else=True)

            # Add external grids at HV buses
            for trafo_idx, trafo in trafos.iterrows():
                pp.create_ext_grid(
                    subnet,
                    bus=trafo["hv_bus"],
                    name=f"3{grid_code}_{str(trafo_idx).zfill(6)}"
                )

            grids.append(subnet)
            logger.debug(f"Extracted grid {lv_index}{grid_code}: {len(subnet.bus)} buses")

        except Exception as e:
            logger.warning(f"Failed to extract grid {grid_code}: {e}")
            continue

    logger.info(f"Successfully extracted {len(grids)} grids using SWF naming convention")
    return grids


def _split_by_naming_swd(
    net: pp.pandapowerNet,
    lv_index: int = 7
) -> List[pp.pandapowerNet]:
    """
    Split network using SWD hierarchical naming convention.

    The chr_name structure uses underscore-separated format:
    NNNNNNN_XXXXXX_YYYYYY_ZZZZZZ_WWWWW

    Where the first part (NNNNNNN) contains:
    Position 1: Netzebene (voltage level) - 7=LV, 5=MV
    Position 2-7: Repeated digits encoding Network+Substation+Branch

    For splitting LV grids:
    - Grid identifier = first part before underscore (e.g., "7137137")
    - This groups all buses/lines belonging to the same physical grid
    - Includes the branch number, which differentiates between transformers
    """
    logger = logging.getLogger(__name__)

    # Extract grid identifiers from all LV buses
    # For buses with underscores, use first part; otherwise use first 7 chars
    lv_buses_df = net.bus[net.bus["chr_name"].astype(str).str.startswith(str(lv_index))].copy()

    if lv_buses_df.empty:
        logger.warning("No LV buses found in network")
        return []

    # Extract grid codes from first part before underscore (or first 7 chars if no underscore)
    def extract_grid_code(name):
        name_str = str(name)
        if '_' in name_str:
            return name_str.split('_')[0]
        else:
            return name_str[:7] if len(name_str) >= 7 else name_str

    lv_buses_df['grid_code'] = lv_buses_df['chr_name'].apply(extract_grid_code)
    grid_codes = sorted(lv_buses_df['grid_code'].unique())

    logger.info(f"Found {len(grid_codes)} unique LV grids in network")
    logger.debug(f"Grid codes: {grid_codes[:10]}...")

    grids = []

    for grid_code in grid_codes:
        try:
            # Get all LV buses for this grid (matching the full grid code)
            # Use the extracted grid_code to find matching buses
            matching_buses = lv_buses_df[lv_buses_df['grid_code'] == grid_code]
            lv_bus_indices = list(matching_buses.index)

            if not lv_bus_indices:
                logger.warning(f"No LV buses found for grid {grid_code}")
                continue

            # Find all transformers connecting to this grid
            # Transformer's LV bus should belong to this grid
            grid_trafos = []
            for t_idx, t_row in net.trafo.iterrows():
                if t_row['lv_bus'] in lv_bus_indices:
                    grid_trafos.append((t_idx, t_row))

            if not grid_trafos:
                logger.debug(f"No transformers found for grid {grid_code}, skipping")
                continue

            # Collect all buses: LV buses + HV buses of transformers
            subbuses = lv_bus_indices.copy()
            for t_idx, t_row in grid_trafos:
                if t_row['hv_bus'] not in subbuses:
                    subbuses.append(t_row['hv_bus'])

            # Extract subnet using pandapower's select_subnet
            subnet = pp.select_subnet(net, buses=subbuses, keep_everything_else=True)

            # Add external grids at HV buses (to make grids independently solvable)
            for t_idx, t_row in grid_trafos:
                hv_bus_in_subnet = t_row['hv_bus']  # This is the original bus index
                # Find the corresponding bus in subnet
                if hv_bus_in_subnet in subnet.bus.index:
                    pp.create_ext_grid(
                        subnet,
                        bus=hv_bus_in_subnet,
                        name=f"ext_grid_{grid_code}_{str(t_idx).zfill(6)}"
                    )

            grids.append(subnet)
            logger.debug(f"Extracted grid {grid_code}: {len(subnet.bus)} buses, "
                       f"{len(subnet.load)} loads, {len(grid_trafos)} trafos, "
                       f"{len(subnet.line)} lines")

        except Exception as e:
            logger.warning(f"Failed to extract grid {grid_code}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            continue

    logger.info(f"Successfully extracted {len(grids)} grids using SWD naming convention")
    return grids


def _split_by_topology(net: pp.pandapowerNet) -> List[pp.pandapowerNet]:
    """
    Split network using topology-based approach.

    This approach works for any network structure by finding connected
    components downstream of each transformer.
    """
    logger = logging.getLogger(__name__)

    # Create network graph once for efficiency
    logger.info("Creating network graph...")
    mg = top.create_nxgraph(net, respect_switches=False)
    logger.info("Graph created successfully")

    grids = []

    for trafo_idx, trafo_row in net.trafo.iterrows():
        try:
            # Extract subnet for this transformer
            lv_bus = trafo_row['lv_bus']
            hv_bus = trafo_row['hv_bus']
            subnet = extract_grid_by_lv_bus_optimized(net, mg, lv_bus, hv_bus, trafo_idx)

            if subnet is not None:
                grids.append(subnet)
                logger.debug(f"Extracted grid {len(grids)}: {len(subnet.bus)} buses, "
                           f"{len(subnet.load)} loads, trafo at bus {lv_bus}")

        except Exception as e:
            logger.warning(f"Failed to extract grid for transformer {trafo_idx}: {e}")
            continue

    logger.info(f"Successfully split into {len(grids)} individual grids")
    return grids


def extract_grid_by_lv_bus_optimized(
    net: pp.pandapowerNet,
    mg,  # Pre-created network graph
    lv_bus: int,
    hv_bus: int,
    trafo_idx: int
) -> Optional[pp.pandapowerNet]:
    """
    Extract a single LV grid starting from an LV bus (optimized version).

    Parameters
    ----------
    net : pp.pandapowerNet
        Complete network
    mg : networkx.Graph
        Pre-created network graph
    lv_bus : int
        LV bus index (downstream side of transformer)
    hv_bus : int
        HV bus index (upstream side of transformer)
    trafo_idx : int
        Transformer index

    Returns
    -------
    pp.pandapowerNet or None
        Subnet containing only this LV grid
    """
    # Get all nodes in the connected component containing lv_bus
    if lv_bus not in mg.nodes():
        return None

    # Find connected component using BFS (breadth-first search)
    connected_buses = set()
    to_visit = [lv_bus]
    visited = set()

    while to_visit:
        bus = to_visit.pop(0)  # Use pop(0) for BFS
        if bus in visited or bus == hv_bus:  # Don't cross to HV side
            continue
        visited.add(bus)
        connected_buses.add(bus)

        # Add neighbors
        for neighbor in mg.neighbors(bus):
            if neighbor not in visited and neighbor != hv_bus:
                to_visit.append(neighbor)

    # Create subnet with only these buses
    subnet = pp.create_empty_network()

    # Copy relevant elements
    bus_mapping = {}
    for old_idx in connected_buses:
        if old_idx in net.bus.index:
            new_idx = len(subnet.bus)
            bus_mapping[old_idx] = new_idx

            bus_data = net.bus.loc[old_idx].to_dict()
            pp.create_bus(subnet, **{k: v for k, v in bus_data.items()
                                     if k in ['vn_kv', 'name', 'type', 'zone', 'in_service']},
                         index=new_idx)

            # Copy geodata if available
            if old_idx in net.bus_geodata.index:
                subnet.bus_geodata.loc[new_idx] = net.bus_geodata.loc[old_idx]

    # Copy transformer with explicit parameters (DSO data has custom types)
    trafo_data = net.trafo.loc[trafo_idx].to_dict()
    if trafo_data['lv_bus'] in bus_mapping:
        # Add HV bus for transformer
        hv_bus_idx = len(subnet.bus)
        pp.create_bus(subnet, vn_kv=trafo_data.get('vn_hv_kv', 20.0),
                     name=f"HV_bus_{trafo_idx}", index=hv_bus_idx)

        # Create transformer with explicit parameters (avoid std_type issues)
        pp.create_transformer_from_parameters(
            subnet,
            hv_bus=hv_bus_idx,
            lv_bus=bus_mapping[trafo_data['lv_bus']],
            sn_mva=trafo_data.get('sn_mva', 0.4),
            vn_hv_kv=trafo_data.get('vn_hv_kv', 20.0),
            vn_lv_kv=trafo_data.get('vn_lv_kv', 0.4),
            vkr_percent=trafo_data.get('vkr_percent', 1.2),
            vk_percent=trafo_data.get('vk_percent', 4.0),
            pfe_kw=trafo_data.get('pfe_kw', 0.1),
            i0_percent=trafo_data.get('i0_percent', 0.1),
            name=trafo_data.get('name', f"Trafo_{trafo_idx}"),
            in_service=trafo_data.get('in_service', True)
        )

    # Copy lines with explicit parameters (DSO data has custom cable types)
    for line_idx, line in net.line.iterrows():
        from_bus = line['from_bus']
        to_bus = line['to_bus']

        if from_bus in bus_mapping and to_bus in bus_mapping:
            pp.create_line_from_parameters(
                subnet,
                from_bus=bus_mapping[from_bus],
                to_bus=bus_mapping[to_bus],
                length_km=line['length_km'],
                r_ohm_per_km=line.get('r_ohm_per_km', 0.0),
                x_ohm_per_km=line.get('x_ohm_per_km', 0.0),
                c_nf_per_km=line.get('c_nf_per_km', 0.0),
                max_i_ka=line.get('max_i_ka', 1.0),
                name=line.get('name', f"Line_{line_idx}"),
                in_service=line.get('in_service', True)
            )

    # Copy loads
    for load_idx, load in net.load.iterrows():
        bus = load['bus']
        if bus in bus_mapping:
            pp.create_load(
                subnet,
                bus=bus_mapping[bus],
                p_mw=load.get('p_mw', 0.0),
                q_mvar=load.get('q_mvar', 0.0),
                name=load.get('name', f"Load_{load_idx}"),
                scaling=load.get('scaling', 1.0),
                in_service=load.get('in_service', True)
            )

            # Copy max_p_mw if it exists
            if 'max_p_mw' in net.load.columns:
                subnet.load.loc[len(subnet.load)-1, 'max_p_mw'] = load.get('max_p_mw')

    return subnet


def save_split_grids(
    grids: List[pp.pandapowerNet],
    output_dir: str,
    prefix: str = "grid",
    save_json: bool = True,
    save_excel: bool = False,
    save_info_csv: bool = True
) -> pd.DataFrame:
    """
    Save split grids to individual files.

    Parameters
    ----------
    grids : list of pp.pandapowerNet
        List of individual grid networks
    output_dir : str
        Directory to save the grids
    prefix : str
        Prefix for filenames (default: "grid")
    save_json : bool
        Save as JSON files
    save_excel : bool
        Save as Excel files
    save_info_csv : bool
        Save a CSV with summary information

    Returns
    -------
    pd.DataFrame
        Summary information about saved grids
    """
    logger = logging.getLogger(__name__)

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Create info dataframe
    df_info = pd.DataFrame(
        columns=["grid_id", "filename", "buses", "loads", "sgens", "trafos", "lines", "ext_grids"]
    )

    logger.info(f"Saving {len(grids)} grids to {output_dir}...")

    for i, grid in enumerate(grids, 1):
        filename = f"{prefix}_{str(i).zfill(4)}"

        try:
            # Save JSON
            if save_json:
                json_path = os.path.join(output_dir, f"{filename}.json")
                pp.to_json(grid, json_path)
                logger.debug(f"Saved {filename}.json")

            # Save Excel
            if save_excel:
                excel_path = os.path.join(output_dir, f"{filename}.xlsx")
                pp.to_excel(grid, excel_path)
                logger.debug(f"Saved {filename}.xlsx")

            # Collect info
            df_info.loc[i-1] = [
                i,
                filename,
                len(grid.bus),
                len(grid.load),
                len(grid.sgen) if hasattr(grid, 'sgen') and not grid.sgen.empty else 0,
                len(grid.trafo),
                len(grid.line),
                len(grid.ext_grid) if hasattr(grid, 'ext_grid') and not grid.ext_grid.empty else 0
            ]

        except Exception as e:
            logger.error(f"Failed to save grid {i}: {e}")
            continue

    # Save info CSV
    if save_info_csv:
        info_path = os.path.join(output_dir, f"_info_{prefix}.csv")
        df_info.to_csv(info_path, index=False)
        logger.info(f"Saved summary info to {info_path}")

    logger.info(f"Successfully saved {len(df_info)} grids")
    return df_info


def analyze_multi_grid_network(
    net: pp.pandapowerNet,
    adapt_networks: bool = True,
    max_grids: int = None
) -> List[Dict[str, Any]]:
    """
    Analyze a multi-grid DSO network by splitting and analyzing each grid.

    Parameters
    ----------
    net : pp.pandapowerNet
        Network containing multiple LV grids
    adapt_networks : bool
        Whether to adapt each grid's structure
    max_grids : int, optional
        Maximum number of grids to analyze (for testing/debugging)

    Returns
    -------
    list of dict
        List of parameter dictionaries, one per grid
    """
    from src.analysis.data_adapter import adapt_dso_network
    from src.analysis.standalone_calculator import StandaloneParameterCalculator

    logger = logging.getLogger(__name__)

    # Split into individual grids
    grids = split_multi_grid_network(net)

    if max_grids:
        grids = grids[:max_grids]
        logger.info(f"Limiting analysis to first {max_grids} grids")

    results = []
    calculator = StandaloneParameterCalculator()

    for i, grid in enumerate(grids, 1):
        try:
            logger.info(f"Analyzing grid {i}/{len(grids)}...")

            # Adapt if requested
            if adapt_networks:
                grid = adapt_dso_network(grid, default_zone='Residential')

            # Calculate parameters
            params = calculator.compute_parameters_with_fallback(
                grid,
                estimate_simultaneous_load=True
            )

            # Add grid identifier
            params['grid_id'] = i
            params['transformer_count'] = len(grid.trafo)

            results.append(params)

        except Exception as e:
            logger.error(f"Failed to analyze grid {i}: {e}")
            continue

    logger.info(f"Successfully analyzed {len(results)}/{len(grids)} grids")
    return results

