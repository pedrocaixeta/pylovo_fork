"""
Validation module for external/DSO network analysis.

This module provides tools to analyze external pandapower networks (e.g., from DSO)
without requiring database access.

Main Components:
- NetworkAdapter: Normalize external networks for analysis
- GridSplitter: Split multi-grid networks into individual grids
- MetricsCalculator: Compute topology metrics without database
- naming_conventions: Parse different naming conventions (SWF, Forchheim)
- config: Configuration management
"""

from .network_adapter import NetworkAdapter, adapt_network
from src.analysis.tools.grid_splitter import GridSplitter, split_network
from .metrics_calculator import MetricsCalculator
from . import naming_conventions

__all__ = [
    'NetworkAdapter',
    'adapt_network',
    'GridSplitter',
    'split_network',
    'MetricsCalculator',
    'analyze_network',
    'naming_conventions',
    'config'
]

