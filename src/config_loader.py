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

# Load Project Root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Load all configurations with correct paths
CONFIG_DATABASE = load_yaml_config("../config/config_database.yaml")
CONFIG_GRID = load_yaml_config("../config/config_grid.yaml")
CONFIG_ANALYSIS = load_yaml_config("../config/config_analysis.yaml")
CONFIG_CLASSIFICATION = load_yaml_config("../config/config_classification.yaml")
CONFIG_CLUSTERING = load_yaml_config("../config/config_clustering.yaml")

# Load database connection configuration from CONFIG_DATABASE
load_dotenv(find_dotenv(), override=True)
DBNAME = os.getenv("DBNAME", CONFIG_DATABASE["DBNAME"])
DBUSER = os.getenv("DBUSER", CONFIG_DATABASE["DBUSER"])
HOST = os.getenv("HOST", CONFIG_DATABASE["HOST"])
PORT = os.getenv("PORT", CONFIG_DATABASE["PORT"])
PASSWORD = os.getenv("PASSWORD", CONFIG_DATABASE["PASSWORD"])
TARGET_SCHEMA = os.getenv("TARGET_SCHEMA", CONFIG_DATABASE["TARGET_SCHEMA"])

USE_INFDB = True if CONFIG_DATABASE["USE_INFDB"] in [True, "True", "true", 1, "1", "on"] else False
INFDB_DBNAME = os.getenv("INFDB_DBNAME", CONFIG_DATABASE.get("INFDB_DBNAME"))
INFDB_USER = os.getenv("INFDB_USER", CONFIG_DATABASE.get("INFDB_USER"))
INFDB_HOST = os.getenv("INFDB_HOST", CONFIG_DATABASE.get("INFDB_HOST"))
INFDB_PORT = os.getenv("INFDB_PORT", CONFIG_DATABASE.get("INFDB_PORT"))
INFDB_PASSWORD = os.getenv("INFDB_PASSWORD", CONFIG_DATABASE.get("INFDB_PASSWORD"))
INFDB_SOURCE_SCHEMA = os.getenv("INFDB_SOURCE_SCHEMA", CONFIG_DATABASE.get("INFDB_SOURCE_SCHEMA", "public"))

# Assign other variables from CONFIG_GRID
RESULT_DIR = os.path.join(os.getcwd(), "results")
ANALYZE_GRIDS = CONFIG_GRID["ANALYZE_GRIDS"]
SAVE_GRID_FOLDER = CONFIG_GRID["SAVE_GRID_FOLDER"]
LOG_LEVEL = CONFIG_GRID["LOG_LEVEL"]
TESTING = CONFIG_GRID.get("TESTING", False)
# Percentage of CPU cores to use for parallel execution
N_JOBS_PERCENT = CONFIG_GRID.get("N_JOBS_PERCENT", 50)
# Determine usable number of cores based on system capability
AVAILABLE_CORES = os.cpu_count() or 1
# Final number of workers rounded from the percentage of cores
N_JOBS = max(1, round(AVAILABLE_CORES * N_JOBS_PERCENT / 100))
K_MEANS_SEED = CONFIG_GRID["K_MEANS_SEED"]

# Assign variables from CONFIG_ANALYSIS
MUNICIPAL_REGISTER = CONFIG_ANALYSIS["MUNICIPAL_REGISTER"]
PLOT_COLOR_DICT = CONFIG_ANALYSIS["PLOT_COLOR_DICT"]

# Regional configuration - determine execution mode based on scale and input type
REGIONAL_SCALE = CONFIG_GRID.get("REGIONAL_SCALE", "postcode")
PLZ = CONFIG_GRID.get("PLZ")
AGS = CONFIG_GRID.get("AGS")

# Validate regional scale
if REGIONAL_SCALE not in ["municipality", "postcode"]:
    raise ValueError(f"Invalid REGIONAL_SCALE: {REGIONAL_SCALE}. Must be 'municipality' or 'postcode'.")

# Determine execution mode based on regional scale and input type
if REGIONAL_SCALE == "postcode":
    if PLZ is None:
        raise ValueError("PLZ must be specified when REGIONAL_SCALE is 'postcode'.")
    
    if isinstance(PLZ, list):
        EXECUTION_MODE = "multiple_plz"
    else:
        EXECUTION_MODE = "single_plz"
        
elif REGIONAL_SCALE == "municipality":
    if AGS is None:
        raise ValueError("AGS must be specified when REGIONAL_SCALE is 'municipality'.")
    
    if isinstance(AGS, list):
        EXECUTION_MODE = "multiple_ags"
    else:
        EXECUTION_MODE = "single_ags"
CSV_FILE_LIST = [
    {"path": os.path.join("raw_data", "postcode.csv"), "table_name": "postcode"},]

### Assign all variables from CONFIG_GRID
VERSION_ID = CONFIG_GRID["VERSION_ID"]
VERSION_COMMENT = CONFIG_GRID["VERSION_COMMENT"]
CONNECTION_AVAILABLE_CABLES = CONFIG_GRID["CONNECTION_AVAILABLE_CABLES"]
RURAL_MAX_HOUSEHOLDS = CONFIG_GRID["RURAL_MAX_HOUSEHOLDS"]
URBAN_MIN_HOUSEHOLDS = CONFIG_GRID["URBAN_MIN_HOUSEHOLDS"]
RURAL_MIN_BUILDING_DISTANCE = CONFIG_GRID["RURAL_MIN_BUILDING_DISTANCE"]
URBAN_MAX_BUILDING_DISTANCE = CONFIG_GRID["URBAN_MAX_BUILDING_DISTANCE"]
MAX_BROWNFIELD_TRAFO_DISTANCE = CONFIG_GRID["MAX_BROWNFIELD_TRAFO_DISTANCE"]

SIM_FACTOR = CONFIG_GRID["SIM_FACTOR"]
PEAK_LOAD_HOUSEHOLD = CONFIG_GRID["PEAK_LOAD_HOUSEHOLD"]
CONSUMER_CATEGORIES = pd.DataFrame(CONFIG_GRID["CONSUMER_CATEGORIES"])
# --- Patch: replace string placeholder references (e.g. 'PEAK_LOAD_HOUSEHOLD') with actual numeric value ---
if not CONSUMER_CATEGORIES.empty and "peak_load" in CONSUMER_CATEGORIES.columns:
    def _resolve_peak_load(val):
        if isinstance(val, str) and val.strip() == "PEAK_LOAD_HOUSEHOLD":
            return PEAK_LOAD_HOUSEHOLD
        return val
    CONSUMER_CATEGORIES["peak_load"] = CONSUMER_CATEGORIES["peak_load"].apply(_resolve_peak_load)
    # enforce numeric (None / null stay as NaN for categories using per m2 metrics)
    CONSUMER_CATEGORIES["peak_load"] = pd.to_numeric(CONSUMER_CATEGORIES["peak_load"], errors="coerce")
EQUIPMENT_DATA = pd.DataFrame(CONFIG_GRID["EQUIPMENT_DATA"])
LARGE_COMPONENT_LOWER_BOUND = CONFIG_GRID["LARGE_COMPONENT_LOWER_BOUND"]
LARGE_COMPONENT_DIVIDER = CONFIG_GRID["LARGE_COMPONENT_DIVIDER"]
VN = CONFIG_GRID["VN"]
V_BAND_LOW = CONFIG_GRID["V_BAND_LOW"]
V_BAND_HIGH = CONFIG_GRID["V_BAND_HIGH"]

# Assign all variables from CONFIG_CLASSIFICATION
CLASSIFICATION_VERSION = CONFIG_CLASSIFICATION["CLASSIFICATION_VERSION"]
CLASSIFICATION_VERSION_COMMENT = CONFIG_CLASSIFICATION["CLASSIFICATION_VERSION_COMMENT"]
CLASSIFICATION_REGION = CONFIG_CLASSIFICATION["CLASSIFICATION_REGION"]
NO_OF_CLUSTERS_ALLOWED = CONFIG_CLASSIFICATION["NO_OF_CLUSTERS_ALLOWED"]
N_SAMPLES = CONFIG_CLASSIFICATION["N_SAMPLES"]
REGION_DICT = CONFIG_CLASSIFICATION["REGION_DICT"]
REGIOSTAR7_DICT = CONFIG_CLASSIFICATION["REGIOSTAR7_DICT"]
REGIO7_REGIO5_GEM_DICT = CONFIG_CLASSIFICATION["REGIO7_REGIO5_GEM_DICT"]

# Assign all variables from CONFIG_CLUSTERING
CLUSTERING_PARAMETERS = CONFIG_CLUSTERING["CLUSTERING_PARAMETERS"]
LIST_OF_CLUSTERING_PARAMETERS = CONFIG_CLUSTERING["LIST_OF_CLUSTERING_PARAMETERS"]
N_CLUSTERS_KMEDOID = CONFIG_CLUSTERING["N_CLUSTERS_KMEDOID"]
N_CLUSTERS_KMEANS = CONFIG_CLUSTERING["N_CLUSTERS_KMEANS"]
N_CLUSTERS_GMM = CONFIG_CLUSTERING["N_CLUSTERS_GMM"]
THRESHOLD_MAX_TRAFO_DIS = CONFIG_CLUSTERING["THRESHOLD_MAX_TRAFO_DIS"]
THRESHOLD_HOUSEHOLDS_PER_BUILDING = CONFIG_CLUSTERING["THRESHOLD_HOUSEHOLDS_PER_BUILDING"]

# Thresholds for clustering parameters
THRESHOLD_AVG_TRAFO_DIS = CONFIG_CLUSTERING["THRESHOLD_AVG_TRAFO_DIS"]
THRESHOLD_NO_HOUSE_CONNECTIONS = CONFIG_CLUSTERING["THRESHOLD_NO_HOUSE_CONNECTIONS"]
THRESHOLD_VSW_PER_BRANCH = CONFIG_CLUSTERING["THRESHOLD_VSW_PER_BRANCH"]
THRESHOLD_NO_HOUSEHOLDS = CONFIG_CLUSTERING["THRESHOLD_NO_HOUSEHOLDS"]