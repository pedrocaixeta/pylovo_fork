import pandapower as pp
import pandas as pd
import numpy as np
import json
import matplotlib.pyplot as plt

def process_and_collect_voltage_data(grids_df, peak_load_residential):
    """
    Processes multiple pandapower networks, runs power flow calculations, and
    collects voltage magnitudes (vm_pu) from all buses into a single DataFrame.

    Parameters:
        bcid_network_map (dict): Dictionary where keys are BCIDs (or identifiers) and
                                 values are their corresponding pandapower networks.

    Returns:
        pandas.DataFrame: DataFrame containing voltage magnitudes for all networks,
                          with identifiers as a column.
    """
    result_data = []  # List to hold voltage data

    for row in grids_df.iterrows():
        bcid = row[1]['bcid']
        grid_json_string = json.dumps(row[1]['grid'])
        net = pp.from_json_string(grid_json_string)
        load_count = len(net.load)
        sim_load = peak_load_residential * (0.07 + (1 - 0.07) * (load_count ** (-3 / 4)))
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

def preprocess_pylovo_network(net, avg_load, min_vm_pu, max_vm_pu):
    """
    Preprocess a pandapower network by deleting existing loads, assigning Gaussian-distributed loads,
    adjusting line lengths, setting voltage constraints, and defining polynomial cost data for external grids.

    Parameters:
        net (pandapowerNet): The pandapower network to preprocess.
        avg_load (float): Average apparent power (MVA) for Gaussian-distributed loads.
        min_vm_pu (float): Minimum allowed per-unit voltage magnitude for buses.
        max_vm_pu (float): Maximum allowed per-unit voltage magnitude for buses.

    Returns:
        pandapowerNet: The updated and preprocessed pandapower network.
    """
    # Delete all loads in the network
    if not net.load.empty:
        # Remove all loads by dropping their indices
        net.load.drop(net.load.index, inplace=True)
    else:
        print("No loads found in the network.")
    # Adjust line lengths for the specific condition
    net.line.loc[net.line[(net.line["from_bus"] == 0) & (net.line["to_bus"] == 2)].index, "length_km"] = 0.05
    # Define polynomial cost data for external grid (if present)
    for ext_grid_idx in net.ext_grid.index:
        pp.create_poly_cost(net, ext_grid_idx, "ext_grid", cp1_eur_per_mw=20, cp0_eur=100)

    # Assign Gaussian-distributed loads to all buses
    std_dev = avg_load * 0.1  # Standard deviation is 20% of the average load
    net = assign_gaussian_loads(net, avg_load=avg_load, std_dev=std_dev, cos_phi=0.95, mode="underexcited")

    # Set voltage magnitude constraints for all buses
    net.bus['min_vm_pu'] = min_vm_pu
    net.bus['max_vm_pu'] = max_vm_pu

    return net


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

def plot_load_and_voltage_distribution(net):
    """
    Plots histograms of load (p_mw) and bus voltage (vm_pu) distributions
    from a pandapower network object.

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network from which to extract load and voltage data.

    Returns
    -------
    fig : matplotlib.figure.Figure
        The Figure object containing the subplots.
    axes : numpy.ndarray of matplotlib.axes._subplots.AxesSubplot
        The array of Axes objects (two subplots).
    """
    # Extract load and voltage data
    loads = net.res_load['p_mw']
    voltages = net.res_bus['vm_pu']

    # Create the subplots
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    # Plot histogram of loads
    axes[0].hist(loads, bins=20, color='skyblue', edgecolor='black')
    axes[0].set_title('Load Distribution')
    axes[0].set_xlabel('Load (MW)')
    axes[0].set_ylabel('Frequency')

    # Plot histogram of bus voltages
    axes[1].hist(voltages, bins=20, color='salmon', edgecolor='black')
    axes[1].set_title('Voltage Distribution')
    axes[1].set_xlabel('Voltage (p.u.)')
    axes[1].set_ylabel('Frequency')

    # Adjust layout
    fig.tight_layout()

    # Return the figure and axes, if further customization is desired
    return fig

def plot_all_voltages_for_plz(voltage_df):
    """
    Plots histograms of bus voltage (vm_pu) distributions
    for all networks of a plz.

    Parameters
    ----------
    net : pandapowerNet
        The pandapower network from which to extract load and voltage data.

    Returns
    -------
    fig : matplotlib.figure.Figure
        The Figure object containing the subplots.
    axes : numpy.ndarray of matplotlib.axes._subplots.AxesSubplot
        The array of Axes objects (two subplots).
    """
    # Create the subplots
    fig, axes = plt.subplots(1, 1, figsize=(12, 6))

    # Plot histogram of bus voltages
    axes.hist(voltage_df['vm_pu'], bins=100, color='black', edgecolor='black')
    axes.set_title('AC Power FLow Bus Voltage Distribution')
    axes.set_xlabel('Voltage (p.u.)')
    axes.set_ylabel('Frequency')

    # Adjust layout
    fig.tight_layout()

    # Return the figure and axes, if further customization is desired
    return fig

