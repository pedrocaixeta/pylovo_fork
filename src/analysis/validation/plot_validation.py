import pandapower as pp
import pandas as pd
from pandapower.plotting.plotly import simple_plotly
import os
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_subgrid_files(base_dir: Path, net_name: str) -> list[Path]:
    """Find all subgrid JSON files for a given network name."""
    subgrid_dir = base_dir / "subgrids" / net_name
    if not subgrid_dir.exists():
        logging.error(f"Subgrid directory not found: {subgrid_dir}")
        return []

    json_files = sorted(list(subgrid_dir.glob("*.json")))
    logging.info(f"Found {len(json_files)} subgrid files in {subgrid_dir}")
    return json_files

def merge_subgrids(json_files: list[Path]) -> pp.pandapowerNet | None:
    """Merge multiple pandapower networks from JSON files into a single network."""
    if not json_files:
        return None

    nets = []
    for json_file in json_files:
        try:
            net = pp.from_json(json_file)
            # Add a dummy external grid to the HV bus of the transformer if it doesn't exist
            # This is required for merge_nets to work correctly.
            if net.trafo.shape[0] > 0 and net.ext_grid.shape[0] == 0:
                hv_bus_idx = net.trafo["hv_bus"].iloc[0]
                if hv_bus_idx in net.bus.index:
                    pp.create_ext_grid(net, bus=hv_bus_idx, vm_pu=1.0, va_degree=0.0)
            nets.append(net)
            logging.info(f"Loaded and prepared subgrid: {json_file.name}")
        except Exception as e:
            logging.warning(f"Could not load or prepare {json_file.name}: {e}. Skipping.")
            continue

    if not nets:
        return None

    # Iteratively merge the rest of the networks
    merged_net = nets[0]
    for net_to_merge in nets[1:]:
        try:
            merged_net = pp.merge_nets(merged_net, net_to_merge, std_prio_on_net1=True)
        except Exception as e:
            logging.warning(f"Could not merge a subgrid: {e}. Skipping.")
            continue

    return merged_net

def main():
    """
    Main function to load, merge, and plot all subgrids.
    """
    # Define paths relative to the script location or project root
    # This assumes a standard project structure. Adjust if necessary.
    try:
        # Assuming execution from project root
        project_root = Path(os.getcwd())
        data_dir = project_root / "grid_data"
        net_name = "SWF_V7" # As per documentation
    except Exception:
        logging.error("Could not determine project paths. Please run from the project root directory.")
        return

    # 1. Find all subgrid JSON files
    subgrid_files = find_subgrid_files(data_dir, net_name)
    if not subgrid_files:
        logging.error("No subgrid files found. Please run the splitter first.")
        return

    # --- Plot a single subgrid for testing ---
    single_grid_file = subgrid_files[0]
    logging.info(f"Attempting to plot single subgrid: {single_grid_file.name}")

    try:
        net = pp.from_json(single_grid_file)
    except Exception as e:
        logging.error(f"Failed to load network {single_grid_file.name}: {e}")
        return

    logging.info(f"Loaded network: {len(net.bus)} buses, {len(net.line)} lines.")

    # Ensure line geodata index matches line index for plotting
    if not net.line.empty and not net.line_geodata.empty:
        # The splitter should have already subsetted the geodata.
        # We just need to ensure the index is aligned.
        net.line_geodata = net.line_geodata.loc[net.line_geodata.index.isin(net.line.index)]
        net.line_geodata.index = net.line.index
        logging.info("Aligned line_geodata index with line index.")

    logging.info("Generating interactive plot for single subgrid...")
    try:
        fig = simple_plotly(net, on_map=True, map_style="open-street-map")

        # Save the plot to an HTML file
        plot_filename = data_dir / f"{net_name}_single_subgrid_plot.html"
        fig.write_html(plot_filename)
        logging.info(f"Plot saved to {plot_filename}")
        print(f"\nInteractive plot has been saved to:\n{plot_filename.resolve()}")
    except Exception as e:
        logging.error(f"Failed to generate plot: {e}")
        import traceback
        traceback.print_exc()

    # --- The original code for merging all subgrids is commented out for now ---
    # # 2. Merge all subgrids into one network
    # combined_net = merge_subgrids(subgrid_files)
    # if combined_net is None:
    #     logging.error("Failed to create a combined network.")
    #     return

    # logging.info(f"Successfully merged {len(subgrid_files)} subgrids.")
    # logging.info(f"Combined network stats: {len(combined_net.bus)} buses, {len(combined_net.line)} lines.")

    # # 3. Plot the combined network
    # # The line geodata index must match the line index for plotting.
    # if not combined_net.line.empty and not combined_net.line_geodata.empty:
    #     # Re-index line_geodata to match the line index.
    #     try:
    #         # Ensure we only use geodata for lines that are in the final merged network
    #         coords = combined_net.line_geodata.loc[combined_net.line_geodata.index.isin(combined_net.line.index)].coords.values
    #         combined_net.line_geodata = pd.DataFrame(data=coords, index=combined_net.line.index, columns=['coords'])
    #         logging.info("Re-indexed line_geodata for the combined network.")
    #     except Exception as e:
    #         logging.error(f"Failed to re-index line_geodata for combined network: {e}")
    #         combined_net.line_geodata = pd.DataFrame(columns=['coords'])


    # logging.info("Generating interactive plot...")
    # # We use 'on_map=False' because the coordinates are Cartesian, not Lat/Lon.
    # fig = simple_plotly(combined_net, on_map=True, map_style="open-street-map")

    # # Save the plot to an HTML file
    # plot_filename = data_dir / f"{net_name}_combined_plot.html"
    # fig.write_html(plot_filename)
    # logging.info(f"Plot saved to {plot_filename}")
    # print(f"\nInteractive plot has been saved to:\n{plot_filename.resolve()}")

if __name__ == "__main__":
    main()

