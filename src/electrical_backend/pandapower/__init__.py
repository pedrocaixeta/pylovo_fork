"""
Pandapower backend implementation.

This subpackage provides the Pandapower-based electrical simulation backend.
Pandapower uses pandas DataFrames to represent network components.

Usage:
    from src.electrical_backend.pandapower import PandapowerBackend
    # or via factory:
    from src.electrical_backend import create_backend
    backend = create_backend("pandapower")
"""

from .backend import PandapowerBackend, PandapowerBackendError

__all__ = ["PandapowerBackend", "PandapowerBackendError"]
