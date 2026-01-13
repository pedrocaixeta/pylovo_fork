"""
pylovo.tools - Utility functions for grid management

Provides programmatic access to common grid management tasks like
deletion and export operations.
"""

import os
import pandas as pd
from typing import List, Optional

from pylovo.grid_generator import GridGenerator
from pylovo.config_loader import PROJECT_ROOT


def delete_networks(plz: int, version_id: str) -> None:
    """
    Delete all networks for a given PLZ and version from the database.

    Args:
        plz: Postal code of networks to delete
        version_id: Version ID of networks to delete

    Example:
        >>> from pylovo.tools import delete_networks
        >>> delete_networks(plz=80803, version_id="1")
    """
    gg = GridGenerator(plz=plz)
    gg.dbc.delete_plz_from_all_tables(plz, version_id)


def export_grid_geodata(plz_list: List[int], output_dir: Optional[str] = None) -> tuple[str, str]:
    """
    Export grid geodata to CSV files for QGIS visualization.

    Args:
        plz_list: List of postal codes to export
        output_dir: Output directory for CSV files (default: PROJECT_ROOT/QGIS)

    Returns:
        Tuple of (line_file_path, bus_file_path)

    Example:
        >>> from pylovo.tools import export_grid_geodata
        >>> line_file, bus_file = export_grid_geodata([80803, 80639])
    """
    # Import here to avoid circular dependencies
    from pylovo.plotting.gis_preparation.io_geodata import save_geodata_as_csv

    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "QGIS")

    os.makedirs(output_dir, exist_ok=True)

    # Determine file names
    if len(plz_list) == 1:
        line_file = os.path.join(output_dir, "lines_single_grid.csv")
        bus_file = os.path.join(output_dir, "bus_single_grid.csv")
    else:
        line_file = os.path.join(output_dir, "lines_multiple_grids.csv")
        bus_file = os.path.join(output_dir, "bus_multiple_grids.csv")

    df_plz = pd.DataFrame({'plz': plz_list})
    save_geodata_as_csv(df_plz=df_plz, data_path_lines=line_file, data_path_bus=bus_file)

    return line_file, bus_file


__all__ = ["delete_networks", "export_grid_geodata"]

