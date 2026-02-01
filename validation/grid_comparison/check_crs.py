import pandapower as pp
import geopandas as gpd
from shapely.geometry import Point
from pylovo.database.database_client import DatabaseClient
import sys

# Paths
REAL_GRID = "/home/breveron/data/pylovo_validation/Forchheim/V8/converted_splitted_data/subnets/regular_nets/LV_028.json"

def check_crs():
    # 1. Real Grid Coords
    net = pp.from_json(REAL_GRID)
    print("Real Grid Coordinates (First 5):")
    print(net.bus_geodata.head())
    
    # 2. PLZ Polygon
    dbc = DatabaseClient()
    query = "SELECT geom, ST_SRID(geom) as srid FROM postcode WHERE plz = 91301"
    try:
        gdf = gpd.read_postgis(query, dbc.conn, geom_col="geom")
        print("\nPLZ Polygon Bounds:")
        print(gdf.bounds)
        print("SRID:", gdf['srid'].iloc[0] if 'srid' in gdf else "Unknown")
        
        # Check if they look compatible
        grid_x_sample = net.bus_geodata.iloc[0].x
        grid_y_sample = net.bus_geodata.iloc[0].y
        
        print(f"\nSample Point: ({grid_x_sample}, {grid_y_sample})")
        
        poly = gdf.unary_union
        point = Point(grid_x_sample, grid_y_sample)
        print(f"Contains? {poly.contains(point)}")
        
    except Exception as e:
        print(f"Error checking polygon: {e}")

if __name__ == "__main__":
    check_crs()
