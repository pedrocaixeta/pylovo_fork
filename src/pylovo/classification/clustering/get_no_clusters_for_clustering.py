import pandas as pd

from pylovo.config_loader import NO_OF_CLUSTERS_ALLOWED
from pylovo.classification.database_communication.database_communication import DatabaseCommunication
from pylovo.plotting.classification import plot_ch_index_for_clustering_algos
import warnings

warnings.filterwarnings('ignore')


def get_no_clusters_for_clustering() -> pd.DataFrame:
    """print and plot best number of clusters for cluster algorithms determined with CH index"""
    # import the dateset of grid parameters
    dc = DatabaseCommunication()
    df_parameters_of_grids = dc.get_clustering_parameters_for_classification_version()

    df_ch_comparison = plot_ch_index_for_clustering_algos(df_plz_parameters=df_parameters_of_grids,
                                                          no_of_clusters_allowed=NO_OF_CLUSTERS_ALLOWED)

    return df_ch_comparison


def main() -> None:
    df_no = get_no_clusters_for_clustering()
    print(df_no)


if __name__ == "__main__":
    main()