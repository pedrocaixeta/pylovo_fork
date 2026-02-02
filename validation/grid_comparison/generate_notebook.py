import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
import os

nb = new_notebook()

# --- Cell 1: Introduction ---
nb.cells.append(new_markdown_cell(r"""
# Interactive Grid Comparison Analysis
This notebook enables interactive comparison of Synthetic Grid Versions against Real Grid Data.

**Features:**
- **Interactive Plotting**: Choose metrics and plot types via dropdowns.
- **Statistical Analysis**: Kolmogorov-Smirnov (KS) tests to quantify distribution similarity.
- **Geographic Analysis**: Visualize grid structures on map.
- **Data Loading**: Auto-detects Real Grid CSVs or allows path configuration.
"""))

# --- Cell 2: Imports ---
nb.cells.append(new_code_cell(r"""
import pandas as pd
import psycopg2
import os
import sys
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
import ipywidgets as widgets
from IPython.display import display
from scipy import stats

# Add project root to path for imports if running locally without install
project_root = Path("../../").resolve()
sys.path.append(str(project_root / "src"))

# Import Refactored Modules
from pylovo.plotting.validation import metric_validation as plotting
from pylovo.plotting.validation import geo_validation
from pylovo.database import database_client

load_dotenv(project_root / ".env")

# Configuration
PLZ = 91301
REAL_METRICS_PATH = Path("results/comparison_metrics.csv")
if not REAL_METRICS_PATH.exists():
    found = list(Path(".").rglob("comparison_metrics.csv"))
    if found:
        REAL_METRICS_PATH = found[0]
"""))

# --- Cell 3: Data Loading Functions ---
nb.cells.append(new_code_cell(r"""
def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get("DBNAME"),
            user=os.environ.get("DBUSER"),
            password=os.environ.get("PASSWORD"),
            host=os.environ.get("HOST"),
            port=os.environ.get("PORT")
        )
        return conn
    except Exception as e:
        print(f"DB Connection Failed: {e}")
        return None

def load_real_metrics(csv_path):
    if not csv_path.exists():
        print(f"WARNING: Real metrics CSV not found at {csv_path}")
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    # ROBUST FILTERING
    real_df = df[df['source'].str.contains('Real', case=False, na=False)]
    if real_df.empty:
        print("Warning: CSV loaded but no 'Real' source found inside.")
    return real_df

def load_synthetic_metrics(conn, plz, versions=None):
    if conn is None: return pd.DataFrame()
    query = f'''
    SELECT 
        gr.version_id, gr.plz, gr.kcid, gr.bcid, gr.grid_result_id,
        cp.no_households, cp.no_household_equ, cp.max_no_of_households_of_a_branch,
        cp.no_branches, cp.max_power_mw, cp.simultaneous_peak_load_mw,
        cp.transformer_mva, cp.avg_trafo_dis, cp.max_trafo_dis,
        cp.max_vsw_of_a_branch, cp.cable_length_km, cp.no_house_connections,
        cp.resistance, cp.reactance
    FROM pylovo.grid_result gr
    JOIN pylovo.clustering_parameters cp ON gr.grid_result_id = cp.grid_result_id
    WHERE gr.plz = {plz}
    '''
    if versions:
        if len(versions) == 1:
            query += f" AND gr.version_id = '{versions[0]}'"
        else:
            query += f" AND gr.version_id IN {tuple(versions)}"
            
    try:
        df = pd.read_sql(query, conn)
        if not df.empty:
            df['source'] = 'Synthetic ' + df['version_id']
        return df
    except Exception as e:
        print(f"Error: {e}")
        return pd.DataFrame()

def get_available_versions(conn):
    if conn is None: return pd.DataFrame()
    try:
        return pd.read_sql("SELECT DISTINCT version_id, version_comment FROM pylovo.version", conn)
    except:
        return pd.DataFrame()
"""))

# --- Cell 4: Load Data ---
nb.cells.append(new_code_cell(r"""
conn = get_db_connection()
versions_df = get_available_versions(conn)
print("Available Versions:")
display(versions_df)

# Load Real
df_real = load_real_metrics(REAL_METRICS_PATH)
if not df_real.empty:
    print(f"Loaded {len(df_real)} Real Grids.")
else:
    print("FAILED TO LOAD REAL GRIDS.")

# Load Synthetic
version_ids = versions_df['version_id'].tolist() if not versions_df.empty else ['1'] 
df_synth = load_synthetic_metrics(conn, PLZ, versions=version_ids)

# Combine
df_all = pd.concat([df_real, df_synth], ignore_index=True)
print(f"Total Grids Loaded: {len(df_all)}")
"""))

# --- Cell 5: Interactive Boxplots ---
nb.cells.append(new_markdown_cell(r"""
## interactive Metric Distribution
Select a metric to compare distributions via Boxplots.
"""))

nb.cells.append(new_code_cell(r"""
numeric_cols = df_all.select_dtypes(include=np.number).columns.tolist()
# Filter out IDs
metrics = [c for c in numeric_cols if c not in ['plz', 'kcid', 'bcid', 'grid_result_id', 'version_id']]

def interactive_boxplot(metric):
    # Using refactored function
    fig = plotting.plot_comparison_distribution_plotly(df_all, metric, title=f"Distribution of {metric}")
    fig.show()

widgets.interact(interactive_boxplot, metric=widgets.Dropdown(options=metrics, value='transformer_mva', description='Metric:'));
"""))

# --- Cell 6: Interactive Histograms ---
nb.cells.append(new_markdown_cell(r"""
## Interactive Histograms
Overlap histograms to analyze distribution shape and tail behavior.
"""))

nb.cells.append(new_code_cell(r"""
def interactive_histogram(metric):
    fig = plotting.plot_comparison_histogram_plotly(df_all, metric, title=f"Histogram of {metric}")
    fig.show()

widgets.interact(interactive_histogram, metric=widgets.Dropdown(options=metrics, value='cable_length_km', description='Metric:'));
"""))

# --- Cell 7: GIS Visualization ---
nb.cells.append(new_markdown_cell(r"""
## Geographic Visualization (GIS)
Visualize the grids on a map.
"""))

nb.cells.append(new_code_cell(r"""
print("Plotting Transformer Overview for PLZ (can take a moment)...")
# Overview of all transformers
try:
    fig_overview = geo_validation.plot_trafo_on_map(PLZ, save_plots=False)
    if fig_overview:
        fig_overview.show()
    else:
        print("No overview figure generated.")
except Exception as e:
    print(f"GIS Overview failed: {e}")
"""))

nb.cells.append(new_code_cell(r"""
# Inspect specific grid (Example: First entry from loaded data)
if not df_synth.empty:
    sample_grid = df_synth.iloc[0]
    kcid = sample_grid['kcid']
    bcid = sample_grid['bcid']
    print(f"Zooming in on Grid KCID={kcid}, BCID={bcid}")
    fig_zoom = geo_validation.plot_grid_on_map_plotly(PLZ, int(kcid), int(bcid), title=f"Grid {kcid}-{bcid}")
    if fig_zoom:
        fig_zoom.show()
"""))

# --- Cell 8: Statistical Analysis ---
nb.cells.append(new_markdown_cell(r"""
## Statistical Comparison (KS-Test)
Mathematically quantify the difference between Real and Synthetic distributions.
"""))

nb.cells.append(new_code_cell(r"""
def calculate_ks_stats(metric):
    if df_real.empty:
        print("Cannot calculate stats: Missing Real Data")
        return
        
    real_vals = df_real[metric].dropna()
    results = []
    
    for ver in df_synth['version_id'].unique():
        synth_vals = df_synth[df_synth['version_id'] == ver][metric].dropna()
        if synth_vals.empty: continue
        
        stat, pval = stats.ks_2samp(real_vals, synth_vals)
        results.append({
            "Version": ver,
            "Metric": metric,
            "KS Statistic": round(stat, 4),
            "P-Value": round(pval, 4), 
            "Real Mean": round(real_vals.mean(), 2),
            "Synth Mean": round(synth_vals.mean(), 2)
        })
    
    if not results: return
    res_df = pd.DataFrame(results)
    display(res_df.style.background_gradient(subset=['KS Statistic'], cmap='Reds'))

widgets.interact(calculate_ks_stats, metric=widgets.Dropdown(options=metrics, value='transformer_mva', description='Metric:'));
"""))

# Write notebook
output_path = "/home/breveron/git/github/pylovo/validation/grid_comparison/interactive_analysis.ipynb"
with open(output_path, 'w') as f:
    nbf.write(nb, f)

print(f"Created notebook at {output_path}")
