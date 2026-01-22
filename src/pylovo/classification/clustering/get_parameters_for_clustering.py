import warnings
from factor_analyzer import FactorAnalyzer

from pylovo.classification.database_communication.database_communication import DatabaseCommunication
from pylovo.classification.clustering import get_parameters_for_clustering

warnings.filterwarnings('ignore')

def print_parameters_for_clustering_for_classification_version() -> list:
    """ print optimal clustering parameter for grid data of classification version
    """
    # get grid data
    dc = DatabaseCommunication()
    df = dc.get_clustering_parameters_for_classification_version()

    # Dropping unnecessary columns
    df.drop(['version_id', 'plz', 'bcid', 'kcid', 'ratio', 'osm_trafo', 'house_distance_km', 'no_connection_buses',
             'resistance', 'reactance', 'simultaneous_peak_load_mw',
             'no_household_equ', 'max_power_mw'], axis=1, inplace=True)

    # Create factor analysis object and perform factor analysis
    fa = FactorAnalyzer()
    fa.fit(df)

    # Check Eigenvalues
    ev = fa.get_eigenvalues()

    # get the eigenvalues larger than 1.
    # --> This is the appropriate number of factors
    no_of_factors = (ev[0] > 1).sum()

    return df


def main():
    get_parameters_for_clustering()


if __name__ == '__main__':
    main()