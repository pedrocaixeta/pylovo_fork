#!/usr/bin/env python3
"""
Script to add testing postcode entries to the database
"""

import os
import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.database.database_client import DatabaseClient
from src.config_loader import TARGET_SCHEMA


def add_testing_postcode(plz: int, testing_plz: int, note: str, coordinates: list):
    """
    Add a testing postcode entry to the database.
    
    Args:
        plz: The PLZ code to add
        testing_plz: The testing PLZ code (reference to existing PLZ)
        note: Description of the testing area
        coordinates: List of [lon, lat] coordinate pairs for the polygon
    """
    dbc = DatabaseClient()
    
    # Create the polygon geometry from coordinates
    # Coordinates should be in format: [[lon1, lat1], [lon2, lat2], ...]
    coord_string = ", ".join([f"{lon} {lat}" for lon, lat in coordinates])
    
    insert_query = f"""
        INSERT INTO {TARGET_SCHEMA}.postcode (plz, testing_plz, note, qkm, population, geom)
        VALUES (
            %s,
            %s,
            %s,
            1.0,  -- 1 km² for testing
            1000, -- 1000 population for testing
            ST_Transform(
                ST_SetSRID(
                    ST_Multi(
                        ST_GeomFromText('POLYGON(({coord_string}))')
                    ),
                    4326
                ),
                3035
            )
        )
        ON CONFLICT (plz) DO UPDATE SET
            testing_plz = EXCLUDED.testing_plz,
            note = EXCLUDED.note,
            qkm = EXCLUDED.qkm,
            population = EXCLUDED.population,
            geom = EXCLUDED.geom;
    """
    
    try:
        with dbc.conn.cursor() as cur:
            cur.execute(insert_query, (plz, testing_plz, note))
            dbc.conn.commit()
        print(f"Successfully added testing postcode {plz} (testing area: {testing_plz})")
    except Exception as e:
        print(f"Error adding testing postcode {plz}: {e}")
        raise
    finally:
        dbc.close()


def main():
    """Add testing postcode entries."""
    print("Adding testing postcode entries...")
    
    # Test area 1: Small square in Munich area
    munich_coords = [
        [11.5, 48.1],  # Southwest
        [11.6, 48.1],  # Southeast  
        [11.6, 48.2],  # Northeast
        [11.5, 48.2],  # Northwest
        [11.5, 48.1]   # Close polygon
    ]
    
    # Test area 2: Small square in Berlin area
    berlin_coords = [
        [13.3, 52.4],  # Southwest
        [13.4, 52.4],  # Southeast
        [13.4, 52.5],  # Northeast
        [13.3, 52.5],  # Northwest
        [13.3, 52.4]   # Close polygon
    ]
    
    # Add testing postcodes
    add_testing_postcode(88888, 80331, "Munich testing area", munich_coords)
    add_testing_postcode(88889, 10115, "Berlin testing area", berlin_coords)
    
    print("Testing postcode entries added successfully!")


if __name__ == "__main__":
    main()
