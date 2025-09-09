#!/usr/bin/env python3
"""
Import Transformers via UI

A command-line interface to launch the transformer map UI for managing transformer positions.

Usage:
    python runme/import/import_transformers_via_ui.py [--host HOST] [--port PORT]
"""

import sys
import argparse
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data_import.transformers_ui import TransformerMapUI


def main():
    """Main entry point for the transformer UI import script."""
    parser = argparse.ArgumentParser(
        description="Launch the transformer map UI for managing transformer positions"
    )
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind the server to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8080, 
        help="Port to bind the server to (default: 8080)"
    )
    
    args = parser.parse_args()
    
    try:
        # Create and run the transformer map UI
        ui = TransformerMapUI(host=args.host, port=args.port)
        ui.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down transformer map UI...")
    except Exception as e:
        print(f"❌ Error starting transformer map UI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
