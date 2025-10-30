"""
Validation module for external/DSO network analysis.

This module provides tools to analyze external pandapower networks (e.g., from DSO)
without requiring database access.

Main Components:
- NetworkAdapter: Normalize external networks for analysis
- MetricsCalculator: Compute topology metrics without database
- LV subgrid splitter utilities
"""

from .network_adapter import NetworkAdapter, adapt_network
from .metrics_calculator import MetricsCalculator

__all__ = [
    'NetworkAdapter',
    'adapt_network',
    'MetricsCalculator',
    'topology_analysis',
    'powerflow_analysis'
]
