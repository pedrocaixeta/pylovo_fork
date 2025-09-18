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

from src.data_import.transformers_ui import main as ui_main


def main():
    """Main entry point for the transformer UI import script."""
    # Simply call the main function from transformers_ui with auto-cleanup enabled
    sys.argv = ['import_transformers_via_ui'] + sys.argv[1:]
    ui_main()


if __name__ == "__main__":
    main()
