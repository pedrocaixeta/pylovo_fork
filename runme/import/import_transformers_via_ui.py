#!/usr/bin/env python3
"""
Import Transformers via UI

A command-line interface to launch the transformer map UI for managing transformer positions.
Includes automatic port detection and cleanup features to prevent common deployment issues.

Usage:
    python runme/import/import_transformers_via_ui.py [--host HOST] [--port PORT] [--debug] [--cleanup]

Features:
    - Automatic port detection (use --port 0)
    - Automatic cleanup of conflicting processes
    - Database connection management
    - Interactive web-based transformer management

Examples:
    # Auto-detect available port (recommended)
    python runme/import/import_transformers_via_ui.py --port 0
    
    # Use specific port with auto-cleanup
    python runme/import/import_transformers_via_ui.py --port 8088
    
    # Clean up database connections
    python runme/import/import_transformers_via_ui.py --port 0 --cleanup
"""

import sys
import argparse
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data_import.transformers_ui import main as ui_main


def main():
    """Main entry point for the transformer UI import script."""
    # Simply call the main function from transformers_ui with auto-cleanup enabled
    sys.argv = ['import_transformers_via_ui'] + sys.argv[1:]
    ui_main()


if __name__ == "__main__":
    main()
