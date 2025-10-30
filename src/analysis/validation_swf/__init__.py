"""
Validation module for LV grid analysis and benchmarking.

This module provides tools for analyzing both synthetic PyLovo networks and
external DSO networks. Key functionality includes:

- Topology metrics calculation (parameter_calculation.py, parameter_calculation_swf.py)
- Network adaptation for external data (network_adapter_swf.py)
- Power flow analysis and validation_swf (powerflow_analysis.py)
- Multi-transformer network splitting (subgrid_splitter_swf.py)
- Shared utilities for validation_swf workflows (utils_swf.py)

The module supports two main workflows:
1. Database-backed analysis of synthetic PyLovo networks
2. Standalone analysis of external DSO/benchmark networks
"""

