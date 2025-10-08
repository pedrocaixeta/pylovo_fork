import yaml
import os
import pandas as pd
from dotenv import load_dotenv, find_dotenv

def load_yaml_config(filepath: str):
    """Loads a YAML configuration file."""
    abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filepath)
    
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Config file not found: {abs_path}")
    
    with open(abs_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def get_required_env_var(var_name: str, description: str) -> str:
    """Get required environment variable with clear error message if missing."""
    value = os.getenv(var_name)
    if value is None:
        print("=" * 80)
        print("❌ MISSING DATABASE CONFIGURATION")
        print("=" * 80)
        print(f"Environment variable '{var_name}' is not set.")
        print(f"Description: {description}")
        print()
        print("📋 SETUP REQUIRED:")
        print("1. Create a .env file in the project root directory")
        print("2. Copy one of the examples from config/config_database.yaml")
        print("3. Update the values with your actual database credentials")
        print()
        print("=" * 80)
        raise ValueError(f"Missing required environment variable: {var_name}")
    return value

# =============================================================================
# PROJECT ROOT AND CONFIG LOADING
# =============================================================================
# Load Project Root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Load all configurations with correct paths
CONFIG_DATABASE = load_yaml_config("../config/config_database.yaml")
CONFIG_GENERATION = load_yaml_config("../config/config_generation.yaml")
CONFIG_ANALYSIS = load_yaml_config("../config/config_analysis.yaml")
CONFIG_CLASSIFICATION = load_yaml_config("../config/config_classification.yaml")
CONFIG_CLUSTERING = load_yaml_config("../config/config_clustering.yaml")

# =============================================================================
# DATABASE CONFIGURATION (from .env file)
# =============================================================================
# Load database connection configuration from .env file
load_dotenv(find_dotenv(), override=True)

# Primary database connection (required)
DBNAME = get_required_env_var("DBNAME", "Database name for Pylovo")
DBUSER = get_required_env_var("DBUSER", "Database username")
HOST = get_required_env_var("HOST", "Database host address")
PORT = get_required_env_var("PORT", "Database port number")
PASSWORD = get_required_env_var("PASSWORD", "Database password")
TARGET_SCHEMA = get_required_env_var("TARGET_SCHEMA", "Target schema name")

# INFDB (external database) connection (optional)
# USE_INFDB = os.getenv("USE_INFDB", "True").lower() in ["true", "1", "on"]
USE_INFDB = CONFIG_DATABASE["USE_INFDB"]
if USE_INFDB:
    INFDB_DBNAME = get_required_env_var("INFDB_DBNAME", "InfDB database name")
    INFDB_USER = get_required_env_var("INFDB_USER", "InfDB username")
    INFDB_HOST = get_required_env_var("INFDB_HOST", "InfDB host address")
    INFDB_PORT = get_required_env_var("INFDB_PORT", "InfDB port number")
    INFDB_PASSWORD = get_required_env_var("INFDB_PASSWORD", "InfDB password")
    INFDB_SOURCE_SCHEMA = os.getenv("INFDB_SOURCE_SCHEMA", "pylovo_input")
else:
    INFDB_DBNAME = None
    INFDB_USER = None
    INFDB_HOST = None
    INFDB_PORT = None
    INFDB_PASSWORD = None
    INFDB_SOURCE_SCHEMA = None

# =============================================================================
# REGIONAL CONFIGURATION (from CONFIG_GENERATION)
# =============================================================================
PLZ = CONFIG_GENERATION.get("PLZ")
AGS = CONFIG_GENERATION.get("AGS")

# Auto-detect regional scale based on which parameter is provided
if PLZ is not None and AGS is not None:
    raise ValueError("Both PLZ and AGS cannot be specified. Please specify either PLZ or AGS.")
elif PLZ is not None:
    REGIONAL_SCALE = "postcode"
    if isinstance(PLZ, list):
        EXECUTION_MODE = "multiple_plz"
    else:
        EXECUTION_MODE = "single_plz"
elif AGS is not None:
    REGIONAL_SCALE = "municipality"
    if isinstance(AGS, list):
        EXECUTION_MODE = "multiple_ags"
    else:
        EXECUTION_MODE = "single_ags"
else:
    raise ValueError("Either PLZ or AGS must be specified in the configuration.")

# =============================================================================
# EXECUTION CONFIGURATION (from CONFIG_GENERATION)
# =============================================================================
ANALYZE_GRIDS = CONFIG_GENERATION["ANALYZE_GRIDS"]
SAVE_GRID_FOLDER = CONFIG_GENERATION["SAVE_GRID_FOLDER"]
LOG_LEVEL = CONFIG_GENERATION["LOG_LEVEL"]
TESTING = CONFIG_GENERATION.get("TESTING", False)

# Parallel execution configuration
N_JOBS_PERCENT = CONFIG_GENERATION.get("N_JOBS_PERCENT", 50)
AVAILABLE_CORES = os.cpu_count() or 1
N_JOBS = max(1, round(AVAILABLE_CORES * N_JOBS_PERCENT / 100))

# Result directory configuration
RESULT_DIR = os.path.join(os.getcwd(), CONFIG_GENERATION.get("RESULT_DIR", "results"))

# Electrical backend configuration
ELECTRICAL_BACKEND = CONFIG_GENERATION.get("ELECTRICAL_BACKEND", "pandapower")

# =============================================================================
# GRID GENERATION CONFIGURATION (from CONFIG_GENERATION)
# =============================================================================
# Version information
VERSION_ID = CONFIG_GENERATION["VERSION_ID"]
VERSION_COMMENT = CONFIG_GENERATION["VERSION_COMMENT"]

# Load calculation parameters
PEAK_LOAD_HOUSEHOLD = CONFIG_GENERATION["PEAK_LOAD_HOUSEHOLD"]
SIM_FACTOR = CONFIG_GENERATION["SIM_FACTOR"]

# Consumer categories for load calculation
CONSUMER_CATEGORIES = pd.DataFrame(CONFIG_GENERATION["CONSUMER_CATEGORIES"])
# Patch: replace string placeholder references (e.g. 'PEAK_LOAD_HOUSEHOLD') with actual numeric value
if not CONSUMER_CATEGORIES.empty and "peak_load" in CONSUMER_CATEGORIES.columns:
    def _resolve_peak_load(val):
        if isinstance(val, str) and val.strip() == "PEAK_LOAD_HOUSEHOLD":
            return PEAK_LOAD_HOUSEHOLD
        return val
    CONSUMER_CATEGORIES["peak_load"] = CONSUMER_CATEGORIES["peak_load"].apply(_resolve_peak_load)
    # enforce numeric (None / null stay as NaN for categories using per m2 metrics)
    CONSUMER_CATEGORIES["peak_load"] = pd.to_numeric(CONSUMER_CATEGORIES["peak_load"], errors="coerce")

# Equipment data
EQUIPMENT_DATA = pd.DataFrame(CONFIG_GENERATION["EQUIPMENT_DATA"])

# =============================================================================
# VOLTAGE PROPERTIES (from CONFIG_GENERATION)
# =============================================================================
VN = CONFIG_GENERATION["VN"]
V_BAND_LOW = CONFIG_GENERATION["V_BAND_LOW"]
V_BAND_HIGH = CONFIG_GENERATION["V_BAND_HIGH"]

# =============================================================================
# CABLE DIMENSIONING PARAMETERS (from CONFIG_GENERATION)
# =============================================================================
# Calculate maximum cable current from equipment data (largest available cable)
# This ensures the current limit is always based on the actual largest cable in the equipment list
MAX_CABLE_CURRENT_KA = EQUIPMENT_DATA[EQUIPMENT_DATA["typ"] == "Cable"]["max_i_a"].max() / 1000  # Convert A to kA

# Load thresholds for different voltage drop limits
SMALL_LOAD_THRESHOLD_KW = CONFIG_GENERATION["SMALL_LOAD_THRESHOLD_KW"]

# Voltage drop limits for consumer connections (as percentage of nominal voltage per km)
VOLTAGE_DROP_SMALL_LOAD_PERCENT_PER_KM = CONFIG_GENERATION["VOLTAGE_DROP_SMALL_LOAD_PERCENT_PER_KM"]
VOLTAGE_DROP_LARGE_LOAD_PERCENT_PER_KM = CONFIG_GENERATION["VOLTAGE_DROP_LARGE_LOAD_PERCENT_PER_KM"]

# Voltage drop limit for feeder cables (total voltage drop as percentage of nominal voltage)
VOLTAGE_DROP_DISTRIBUTION_PERCENT = CONFIG_GENERATION["VOLTAGE_DROP_DISTRIBUTION_PERCENT"]

# Cables available for consumer connections (from feeder to buildings)
CONSUMER_CONNECTION_AVAILABLE_CABLES = CONFIG_GENERATION["CONSUMER_CONNECTION_AVAILABLE_CABLES"]

# =============================================================================
# SETTLEMENT TYPE THRESHOLDS (from CONFIG_GENERATION)
# =============================================================================
RURAL_MAX_HOUSEHOLDS = CONFIG_GENERATION["RURAL_MAX_HOUSEHOLDS"]
URBAN_MIN_HOUSEHOLDS = CONFIG_GENERATION["URBAN_MIN_HOUSEHOLDS"]
RURAL_MIN_BUILDING_DISTANCE = CONFIG_GENERATION["RURAL_MIN_BUILDING_DISTANCE"]
URBAN_MAX_BUILDING_DISTANCE = CONFIG_GENERATION["URBAN_MAX_BUILDING_DISTANCE"]

# =============================================================================
# GRID GENERATION PARAMETERS (from CONFIG_GENERATION)
# =============================================================================
MAX_BROWNFIELD_TRAFO_DISTANCE = CONFIG_GENERATION["MAX_BROWNFIELD_TRAFO_DISTANCE"]
LARGE_COMPONENT_LOWER_BOUND = CONFIG_GENERATION["LARGE_COMPONENT_LOWER_BOUND"]
LARGE_COMPONENT_DIVIDER = CONFIG_GENERATION["LARGE_COMPONENT_DIVIDER"]
K_MEANS_SEED = CONFIG_GENERATION["K_MEANS_SEED"]

# =============================================================================
# ANALYSIS CONFIGURATION (from CONFIG_ANALYSIS)
# =============================================================================
MUNICIPAL_REGISTER = CONFIG_ANALYSIS["MUNICIPAL_REGISTER"]
PLOT_COLOR_DICT = CONFIG_ANALYSIS["PLOT_COLOR_DICT"]

# =============================================================================
# CLASSIFICATION CONFIGURATION (from CONFIG_CLASSIFICATION)
# =============================================================================
CLASSIFICATION_VERSION = CONFIG_CLASSIFICATION["CLASSIFICATION_VERSION"]
CLASSIFICATION_VERSION_COMMENT = CONFIG_CLASSIFICATION["CLASSIFICATION_VERSION_COMMENT"]
CLASSIFICATION_REGION = CONFIG_CLASSIFICATION["CLASSIFICATION_REGION"]
NO_OF_CLUSTERS_ALLOWED = CONFIG_CLASSIFICATION["NO_OF_CLUSTERS_ALLOWED"]
N_SAMPLES = CONFIG_CLASSIFICATION["N_SAMPLES"]
REGION_DICT = CONFIG_CLASSIFICATION["REGION_DICT"]
REGIOSTAR7_DICT = CONFIG_CLASSIFICATION["REGIOSTAR7_DICT"]
REGIO7_REGIO5_GEM_DICT = CONFIG_CLASSIFICATION["REGIO7_REGIO5_GEM_DICT"]

# =============================================================================
# CLUSTERING CONFIGURATION (from CONFIG_CLUSTERING)
# =============================================================================
CLUSTERING_PARAMETERS = CONFIG_CLUSTERING["CLUSTERING_PARAMETERS"]
LIST_OF_CLUSTERING_PARAMETERS = CONFIG_CLUSTERING["LIST_OF_CLUSTERING_PARAMETERS"]
N_CLUSTERS_KMEDOID = CONFIG_CLUSTERING["N_CLUSTERS_KMEDOID"]
N_CLUSTERS_KMEANS = CONFIG_CLUSTERING["N_CLUSTERS_KMEANS"]
N_CLUSTERS_GMM = CONFIG_CLUSTERING["N_CLUSTERS_GMM"]

# Clustering thresholds
THRESHOLD_MAX_TRAFO_DIS = CONFIG_CLUSTERING["THRESHOLD_MAX_TRAFO_DIS"]
THRESHOLD_HOUSEHOLDS_PER_BUILDING = CONFIG_CLUSTERING["THRESHOLD_HOUSEHOLDS_PER_BUILDING"]
THRESHOLD_AVG_TRAFO_DIS = CONFIG_CLUSTERING["THRESHOLD_AVG_TRAFO_DIS"]
THRESHOLD_NO_HOUSE_CONNECTIONS = CONFIG_CLUSTERING["THRESHOLD_NO_HOUSE_CONNECTIONS"]
THRESHOLD_VSW_PER_BRANCH = CONFIG_CLUSTERING["THRESHOLD_VSW_PER_BRANCH"]
THRESHOLD_NO_HOUSEHOLDS = CONFIG_CLUSTERING["THRESHOLD_NO_HOUSEHOLDS"]

# =============================================================================
# DATA IMPORT CONFIGURATION (only relevant without InfDB)
# =============================================================================
CSV_FILE_LIST = [
    {"path": os.path.join("raw_data", "postcode.csv"), "table_name": "postcode"},
]