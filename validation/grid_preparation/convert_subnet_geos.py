import pandapower as pp
import pandapower.plotting as pplot
import os
from tqdm import tqdm
import glob

def fix_subnet_geos():
    base_dir = "/home/breveron/git/github/pylovo/validation/data/subnets"
    
    # Try import from correct location
    try:
        from pandapower.plotting.geo import convert_geodata_to_geojson
    except ImportError:
        try:
            from pandapower.plotting import convert_geodata_to_geojson
        except ImportError:
            print("ERROR: convert_geodata_to_geojson not found in pandapower.plotting / .geo")
            return

    # Find all JSON files in subdirectories
    pattern = os.path.join(base_dir, "**", "*.json")
    files = glob.glob(pattern, recursive=True)
    
    print(f"Found {len(files)} subnets to process.")
    
    success_count = 0
    fail_count = 0
    
    for fpath in tqdm(files):
        try:
            net = pp.from_json(fpath)
            
            # Apply conversion
            convert_geodata_to_geojson(net, delete=False)
            
            # Overwrite JSON
            pp.to_json(net, fpath)
            
            # Also overwrite Excel to keep sync
            excel_path = fpath.replace(".json", ".xlsx")
            if os.path.exists(excel_path):
                 pp.to_excel(net, excel_path)
            
            success_count += 1
        except Exception as e:
            print(f"Failed to process {os.path.basename(fpath)}: {e}")
            fail_count += 1
            
    print(f"Done. Success: {success_count}, Fail: {fail_count}")

if __name__ == "__main__":
    fix_subnet_geos()
