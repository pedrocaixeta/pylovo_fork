
import os
import sys
import psycopg2
from pathlib import Path
# from dotenv import load_dotenv

# Add src to path
project_root = Path.cwd()
sys.path.append(str(project_root / "src"))

from pylovo.analysis.parameter_calculation import ParameterCalculator
from pylovo.config_loader import VERSION_ID

# load_dotenv(project_root / ".env")
env_path = project_root / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"')

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

def backfill_parameters():
    conn = get_db_connection()
    if not conn:
        return

    cur = conn.cursor()
    
    # Identify missing grids
    print("Identifying missing grids...")
    cur.execute("""
        SELECT plz, kcid, bcid 
        FROM pylovo.grid_result 
        WHERE grid_result_id NOT IN (SELECT grid_result_id FROM pylovo.clustering_parameters)
        AND version_id = %s
    """, (VERSION_ID,))
    
    missing_grids = cur.fetchall()
    print(f"Found {len(missing_grids)} grids missing parameters for version {VERSION_ID}.")
    
    if not missing_grids:
        print("No backfill needed.")
        return

    # Group by PLZ to optimize ParameterCalculator initialization
    grids_by_plz = {}
    for plz, kcid, bcid in missing_grids:
        if plz not in grids_by_plz:
            grids_by_plz[plz] = []
        grids_by_plz[plz].append((kcid, bcid))
    
    print(f"Processing {len(grids_by_plz)} unique PLZs.")
    
    for plz, grids in grids_by_plz.items():
        print(f"Processing PLZ {plz} ({len(grids)} grids)...")
        
        # Initialize Calculator for this PLZ
        calc = ParameterCalculator()
        calc.plz = plz # Manually set PLZ since we are bypassing standard flow
        
        # Ensure PLZ-level analysis is done (required for lookups)
        # We rely on calc_parameters_per_plz checking flags internally
        try:
             calc.calc_parameters_per_plz(plz)
        except Exception as e:
             print(f"  Error enabling PLZ-level params for {plz}: {e}")
             continue

        success_count = 0
        for kcid, bcid in grids:
            try:
                calc.calc_grid_parameters(bcid, kcid)
                success_count += 1
            except Exception as e:
                print(f"  Failed for Grid {kcid}-{bcid}: {e}")
                
        print(f"  Completed {success_count}/{len(grids)} for PLZ {plz}")
        
    conn.close()
    print("Backfill complete.")

if __name__ == "__main__":
    backfill_parameters()
