import pandapower as pp
import pandas as pd
import numpy as np
import json
import matplotlib.pyplot as plt
from typing import Dict, List, Tuple, Optional, Union
import warnings
import logging
import sys
import os
from pathlib import Path

from src.utils import oneSimultaneousLoad, create_logger

# Configure logging using the utility function from utils.py
log_dir = Path(__file__).resolve().parent.parent / 'log'
log_dir.mkdir(exist_ok=True)
log_file = log_dir / 'grid_validation.log'
logger = create_logger('grid_validation', str(log_file), logging.INFO)

# Constants for load scaling
DEFAULT_MIN_VM_PU = 0.9
DEFAULT_MAX_VM_PU = 1.1
DEFAULT_COS_PHI = 0.95
DEFAULT_LOAD_STD_RATIO = 0.1


def process_and_collect_voltage_data(grids_df, peak_load_residential):
    """
    Processes multiple pandapower networks, runs power flow calculations, and
    collects voltage magnitudes (vm_pu) from all buses into a single DataFrame.

    Parameters
    ----------
    grids_df : pd.DataFrame
        DataFrame containing grid data with 'bcid' and 'grid' columns.
    peak_load_residential : float
        Peak residential load in MVA for scaling load assignment.

    Returns
    -------
    pd.DataFrame
        DataFrame containing voltage magnitudes for all networks,
        with BCIDs as identifiers.
    """
    result_data = []  # List to hold voltage data

    for row in grids_df.iterrows():
        bcid = row[1]['bcid']
        grid_json_string = json.dumps(row[1]['grid'])
        net = pp.from_json_string(grid_json_string)
        load_count = len(net.load)
        # Use oneSimultaneousLoad from utils.py to avoid double hard-coding
        sim_load = oneSimultaneousLoad(peak_load_residential, load_count, sim_factor=0.07)
        preprocess_pylovo_network(net, avg_load=sim_load, min_vm_pu=0.95, max_vm_pu=1.05)
        try:
            pp.runpp(net)  # Perform power flow calculation on the current network
            voltages = net.res_bus['vm_pu']  # Extract voltage magnitudes
            for bus, voltage in voltages.items():
                result_data.append({"BCID": bcid, "Bus": bus, "vm_pu": voltage})
        except:
            print(f"Network from {bcid} could not be generated")

    # Convert result_data to a pandas DataFrame
    voltage_df = pd.DataFrame(result_data)
    return voltage_df

def preprocess_pylovo_network(
    net: pp.pandapowerNet,
    avg_load: float,
    min_vm_pu: float = DEFAULT_MIN_VM_PU,
    max_vm_pu: float = DEFAULT_MAX_VM_PU,
    cos_phi: float = DEFAULT_COS_PHI,
    load_std_ratio: float = DEFAULT_LOAD_STD_RATIO,
    adjust_transformer_line: bool = True
) -> pp.pandapowerNet:
    """
    Preprocess a pandapower network for power flow analysis by setting up loads,
    voltage constraints, and cost functions.

    This function prepares a PyLovo-generated network for validation by:
    - Removing existing loads
    - Assigning new Gaussian-distributed loads
    - Setting voltage constraints
    - Adjusting specific line parameters (if needed)
    - Adding cost functions for external grids

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network to preprocess.
    avg_load : float
        Average apparent power (MVA) for Gaussian-distributed loads.
    min_vm_pu : float, optional
        Minimum allowed per-unit voltage magnitude for buses (default: 0.95).
    max_vm_pu : float, optional
        Maximum allowed per-unit voltage magnitude for buses (default: 1.05).
    cos_phi : float, optional
        Power factor of the loads (default: 0.95).
    load_std_ratio : float, optional
        Ratio of standard deviation to average load (default: 0.1).
    adjust_transformer_line : bool, optional
        Whether to adjust specific transformer line lengths (default: True).

    Returns
    -------
    pandapowerNet
        The updated and preprocessed pandapower network.
    """
    # Validate inputs
    if avg_load <= 0:
        raise ValueError(f"avg_load must be positive, got {avg_load}")
    if not (0 < min_vm_pu < max_vm_pu <= 2):
        raise ValueError(f"Invalid voltage limits: min={min_vm_pu}, max={max_vm_pu}")
    if not (0 < cos_phi <= 1):
        raise ValueError(f"cos_phi must be between 0 and 1, got {cos_phi}")

    # Clear existing loads
    _clear_network_loads(net)

    # Adjust specific line parameters for transformer connections
    if adjust_transformer_line:
        _adjust_transformer_line_length(net, from_bus=0, to_bus=2, length_km=0.05)

    # Add cost functions for external grids
    _add_external_grid_costs(net, cp1_eur_per_mw=20, cp0_eur=100)

    # Assign new Gaussian-distributed loads
    std_dev = avg_load * load_std_ratio
    assign_gaussian_loads(
        net,
        avg_load=avg_load,
        std_dev=std_dev,
        cos_phi=cos_phi,
        mode="underexcited"
    )

    # Set voltage magnitude constraints
    net.bus['min_vm_pu'] = min_vm_pu
    net.bus['max_vm_pu'] = max_vm_pu

    return net


def _clear_network_loads(net: pp.pandapowerNet) -> None:
    """
    Remove all loads from a pandapower network.

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network to modify.
    """
    if not net.load.empty:
        net.load.drop(net.load.index, inplace=True)
        logger.debug(f"Cleared all existing loads from network")


def _adjust_transformer_line_length(
    net: pp.pandapowerNet,
    from_bus: int,
    to_bus: int,
    length_km: float
) -> None:
    """
    Adjust line length for a specific connection (typically transformer line).

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network to modify.
    from_bus : int
        Source bus index.
    to_bus : int
        Destination bus index.
    length_km : float
        New line length in kilometers.
    """
    mask = (net.line["from_bus"] == from_bus) & (net.line["to_bus"] == to_bus)
    matching_lines = net.line[mask]

    if not matching_lines.empty:
        net.line.loc[matching_lines.index, "length_km"] = length_km
        logger.debug(f"Adjusted line length from bus {from_bus} to {to_bus}: {length_km} km")


def _add_external_grid_costs(
    net: pp.pandapowerNet,
    cp1_eur_per_mw: float,
    cp0_eur: float
) -> None:
    """
    Add polynomial cost functions to all external grids in the network.

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network to modify.
    cp1_eur_per_mw : float
        Linear cost coefficient (EUR/MW).
    cp0_eur : float
        Constant cost term (EUR).
    """
    for ext_grid_idx in net.ext_grid.index:
        pp.create_poly_cost(
            net,
            ext_grid_idx,
            "ext_grid",
            cp1_eur_per_mw=cp1_eur_per_mw,
            cp0_eur=cp0_eur
        )

    if len(net.ext_grid) > 0:
        logger.debug(f"Added cost functions to {len(net.ext_grid)} external grid(s)")


def assign_random_loads(net, load_range, cos_phi, mode):
    """
    Assigns random loads to all buses in a given pandapower network.

    Parameters:
        net (pandapowerNet): The pandapower network where loads are to be added.
        load_range (tuple): Range of apparent power (MVA) for the loads, e.g., (0.002, 0.03).
        cos_phi (float): Power factor of the load.
        mode (str): "ind" for inductive or "cap" for capacitive behavior.

    Returns:
        pandapowerNet: The updated pandapower network with the added loads.
    """
    # Get all buses in the network
    buses = [bus for bus in net.bus.index.tolist() if bus != 1]

    for bus in buses:
        # Generate a random apparent power (sn_mva) within the specified range
        sn_mva = np.random.uniform(load_range[0], load_range[1])

        # Create a load on the bus with the generated apparent power
        pp.create_load_from_cosphi(
            net=net,
            bus=bus,
            sn_mva=sn_mva,
            cos_phi=cos_phi,
            mode=mode,
            name=f"Load at Bus {bus}"
        )

    print(f"Random loads assigned to all {len(buses)} buses in the network.")
    return net

def assign_gaussian_loads(net, avg_load, std_dev, cos_phi, mode):
    """
    Assigns loads to all buses in the network using a Gaussian (normal) distribution.

    Parameters:
        net (pandapowerNet): The pandapower network where loads are to be added.
        avg_load (float): Average apparent power (MVA) for the loads.
        std_dev (float): Standard deviation of the apparent power values.
        cos_phi (float): Power factor of the load.
        mode (str): "ind" for inductive or "cap" for capacitive behavior.
        load_range (tuple): A tuple (min, max) specifying the allowable range of apparent power (MVA).

    Returns:
        pandapowerNet: The updated pandapower network with the added loads.
    """
    # Get all buses in the network, excluding a swing bus or a specific bus if necessary
    buses = [bus for bus in net.bus.index.tolist() if bus != 1]

    for bus in buses:
        # Generate a random apparent power (sn_mva) from a Gaussian distribution
        sn_mva = np.random.normal(loc=avg_load, scale=std_dev)

        # Create a load on the bus with the generated apparent power
        pp.create_load_from_cosphi(
            net=net,
            bus=bus,
            sn_mva=sn_mva,
            cos_phi=cos_phi,
            mode=mode,
            name=f"Load at Bus {bus}"
        )

    return net



# ==================================================================================
# NEW ANALYSIS FUNCTIONS FOR POWER FLOW VALIDATION
# ==================================================================================

def calculate_network_metrics(net: pp.pandapowerNet) -> Dict[str, float]:
    """
    Calculate comprehensive metrics for a power network after power flow analysis.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network with completed power flow results.

    Returns
    -------
    dict
        Dictionary containing various network performance metrics.

    Raises
    ------
    ValueError
        If power flow results are not available.
    """
    if net.res_bus.empty:
        raise ValueError("No power flow results found. Run pp.runpp(net) first.")

    metrics = {}

    # Voltage metrics
    voltages = net.res_bus['vm_pu']
    metrics['voltage_mean'] = float(voltages.mean())
    metrics['voltage_std'] = float(voltages.std())
    metrics['voltage_min'] = float(voltages.min())
    metrics['voltage_max'] = float(voltages.max())
    metrics['voltage_violations_low'] = int((voltages < 0.95).sum())
    metrics['voltage_violations_high'] = int((voltages > 1.05).sum())
    metrics['voltage_violation_pct'] = float(
        (metrics['voltage_violations_low'] + metrics['voltage_violations_high']) / len(voltages) * 100
    )

    # Load metrics
    if not net.res_load.empty:
        metrics['total_load_p_mw'] = float(net.res_load['p_mw'].sum())
        metrics['total_load_q_mvar'] = float(net.res_load['q_mvar'].sum())
        metrics['avg_load_p_mw'] = float(net.res_load['p_mw'].mean())
        metrics['max_load_p_mw'] = float(net.res_load['p_mw'].max())

    # Line loading metrics
    if not net.res_line.empty:
        line_loading = net.res_line['loading_percent']
        metrics['line_loading_mean'] = float(line_loading.mean())
        metrics['line_loading_max'] = float(line_loading.max())
        metrics['line_overloads'] = int((line_loading > 100).sum())
        metrics['line_overload_pct'] = float(metrics['line_overloads'] / len(line_loading) * 100)

    # Transformer loading metrics
    if not net.res_trafo.empty:
        trafo_loading = net.res_trafo['loading_percent']
        metrics['trafo_loading_mean'] = float(trafo_loading.mean())
        metrics['trafo_loading_max'] = float(trafo_loading.max())
        metrics['trafo_overloads'] = int((trafo_loading > 100).sum())

    # Loss metrics
    if not net.res_line.empty:
        metrics['total_line_losses_mw'] = float(net.res_line['pl_mw'].sum())
    if not net.res_trafo.empty:
        metrics['total_trafo_losses_mw'] = float(net.res_trafo['pl_mw'].sum())

    # External grid metrics
    if not net.res_ext_grid.empty:
        metrics['ext_grid_p_mw'] = float(net.res_ext_grid['p_mw'].sum())
        metrics['ext_grid_q_mvar'] = float(net.res_ext_grid['q_mvar'].sum())

    return metrics


def check_voltage_violations(
    net: pp.pandapowerNet,
    min_vm_pu: float = DEFAULT_MIN_VM_PU,
    max_vm_pu: float = DEFAULT_MAX_VM_PU
) -> pd.DataFrame:
    """
    Identify buses with voltage violations.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network with completed power flow results.
    min_vm_pu : float, optional
        Minimum acceptable voltage in per unit (default: 0.95).
    max_vm_pu : float, optional
        Maximum acceptable voltage in per unit (default: 1.05).

    Returns
    -------
    pd.DataFrame
        DataFrame containing information about buses with voltage violations.
    """
    if net.res_bus.empty:
        raise ValueError("No power flow results found. Run pp.runpp(net) first.")

    violations = []

    for bus_idx in net.res_bus.index:
        vm_pu = net.res_bus.at[bus_idx, 'vm_pu']

        if vm_pu < min_vm_pu:
            violations.append({
                'bus': bus_idx,
                'voltage_pu': vm_pu,
                'violation_type': 'undervoltage',
                'deviation_pu': min_vm_pu - vm_pu,
                'deviation_pct': (min_vm_pu - vm_pu) / min_vm_pu * 100
            })
        elif vm_pu > max_vm_pu:
            violations.append({
                'bus': bus_idx,
                'voltage_pu': vm_pu,
                'violation_type': 'overvoltage',
                'deviation_pu': vm_pu - max_vm_pu,
                'deviation_pct': (vm_pu - max_vm_pu) / max_vm_pu * 100
            })

    return pd.DataFrame(violations)


def check_line_overloads(
    net: pp.pandapowerNet,
    threshold_pct: float = 100.0
) -> pd.DataFrame:
    """
    Identify lines with loading above threshold.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network with completed power flow results.
    threshold_pct : float, optional
        Loading threshold in percent (default: 100.0).

    Returns
    -------
    pd.DataFrame
        DataFrame containing information about overloaded lines.
    """
    if net.res_line.empty:
        raise ValueError("No power flow results found. Run pp.runpp(net) first.")

    overloads = []

    for line_idx in net.res_line.index:
        loading = net.res_line.at[line_idx, 'loading_percent']

        if loading > threshold_pct:
            overloads.append({
                'line': line_idx,
                'from_bus': net.line.at[line_idx, 'from_bus'],
                'to_bus': net.line.at[line_idx, 'to_bus'],
                'loading_pct': loading,
                'overload_pct': loading - threshold_pct,
                'p_from_mw': net.res_line.at[line_idx, 'p_from_mw'],
                'q_from_mvar': net.res_line.at[line_idx, 'q_from_mvar']
            })

    return pd.DataFrame(overloads)


def analyze_network_losses(net: pp.pandapowerNet) -> Dict[str, float]:
    """
    Analyze power losses in the network.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network with completed power flow results.

    Returns
    -------
    dict
        Dictionary containing loss analysis metrics.
    """
    if net.res_line.empty and net.res_trafo.empty:
        raise ValueError("No power flow results found. Run pp.runpp(net) first.")

    losses = {}

    # Line losses
    if not net.res_line.empty:
        losses['total_line_losses_mw'] = float(net.res_line['pl_mw'].sum())
        losses['avg_line_losses_mw'] = float(net.res_line['pl_mw'].mean())
        losses['max_line_losses_mw'] = float(net.res_line['pl_mw'].max())
        losses['line_count'] = len(net.res_line)

    # Transformer losses
    if not net.res_trafo.empty:
        losses['total_trafo_losses_mw'] = float(net.res_trafo['pl_mw'].sum())
        losses['avg_trafo_losses_mw'] = float(net.res_trafo['pl_mw'].mean())
        losses['max_trafo_losses_mw'] = float(net.res_trafo['pl_mw'].max())
        losses['trafo_count'] = len(net.res_trafo)

    # Total losses
    total_losses = 0
    if 'total_line_losses_mw' in losses:
        total_losses += losses['total_line_losses_mw']
    if 'total_trafo_losses_mw' in losses:
        total_losses += losses['total_trafo_losses_mw']

    losses['total_losses_mw'] = total_losses

    # Loss percentage
    if not net.res_load.empty:
        total_load = net.res_load['p_mw'].sum()
        if total_load > 0:
            losses['loss_percentage'] = float(total_losses / total_load * 100)

    return losses




def generate_validation_report(
    net: pp.pandapowerNet,
    bcid: Optional[str] = None
) -> Dict[str, Union[Dict, pd.DataFrame]]:
    """
    Generate a comprehensive validation report for a network.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network with completed power flow results.
    bcid : str, optional
        Building cluster ID for identification.

    Returns
    -------
    dict
        Dictionary containing metrics, violations, and analysis results.
    """
    report = {
        'bcid': bcid,
        'metrics': calculate_network_metrics(net),
        'voltage_violations': check_voltage_violations(net),
        'line_overloads': check_line_overloads(net),
        'losses': analyze_network_losses(net)
    }

    # Add convergence status
    report['converged'] = net.converged if hasattr(net, 'converged') else True

    # Add network size info
    report['network_info'] = {
        'num_buses': len(net.bus),
        'num_lines': len(net.line),
        'num_loads': len(net.load),
        'num_transformers': len(net.trafo) if hasattr(net, 'trafo') else 0,
        'num_ext_grids': len(net.ext_grid)
    }

    return report


def compare_multiple_scenarios(
    net: pp.pandapowerNet,
    scenarios: Dict[str, Dict[str, float]]
) -> pd.DataFrame:
    """
    Compare network performance under multiple load scenarios.

    Parameters
    ----------
    net : pandapowerNet
        Base pandapower network (will be copied for each scenario).
    scenarios : dict
        Dictionary of scenario definitions. Each scenario contains load parameters.
        Example: {'low_load': {'avg_load': 0.01, 'std_dev': 0.002}, ...}

    Returns
    -------
    pd.DataFrame
        DataFrame comparing metrics across all scenarios.
    """
    results = []

    for scenario_name, params in scenarios.items():
        # Create a copy of the network
        net_copy = pp.from_json_string(pp.to_json(net))

        try:
            # Clear and assign loads
            _clear_network_loads(net_copy)
            assign_gaussian_loads(
                net_copy,
                avg_load=params.get('avg_load', 0.01),
                std_dev=params.get('std_dev', 0.001),
                cos_phi=params.get('cos_phi', DEFAULT_COS_PHI),
                mode=params.get('mode', 'underexcited')
            )

            # Run power flow
            pp.runpp(net_copy)

            # Calculate metrics
            metrics = calculate_network_metrics(net_copy)
            metrics['scenario'] = scenario_name
            metrics['converged'] = True
            results.append(metrics)

        except Exception as e:
            logger.warning(f"Scenario '{scenario_name}' failed: {e}")
            results.append({
                'scenario': scenario_name,
                'converged': False,
                'error': str(e)
            })

    return pd.DataFrame(results)


