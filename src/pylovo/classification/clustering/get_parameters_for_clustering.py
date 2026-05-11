import warnings
from factor_analyzer import FactorAnalyzer

from pylovo.classification.database_communication.database_communication import DatabaseCommunication
from pylovo.plotting.classification import get_parameters_for_clustering as select_clustering_parameters

warnings.filterwarnings('ignore')

def get_parameters_for_clustering() -> list:
    """Return optimal clustering parameters for the active classification version."""
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
    no_of_factors = int((ev[0] > 1).sum())
    if no_of_factors <= 0:
        no_of_factors = 1

    return select_clustering_parameters(df_plz_parameters=df, n_comps=no_of_factors)


def main():
    print(get_parameters_for_clustering())


if __name__ == '__main__':
    main()