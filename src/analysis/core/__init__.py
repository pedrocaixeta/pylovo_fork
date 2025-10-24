"""
Core analysis module for synthetic grid analysis.

This module contains the original analysis functions that work with
PyLovo's database for synthetic grid generation and analysis.

Main Components:
- topology_analysis: Compute topology metrics for grids (ParameterCalculator)
- powerflow_analysis: Power flow calculations and validation
"""

# Note: We don't import here to avoid database dependencies
# Import these modules explicitly when needed:
# from src.analysis.core.topology_analysis import ParameterCalculator
# from src.analysis.core.powerflow_analysis import ...

__all__ = ['topology_analysis', 'powerflow_analysis']

