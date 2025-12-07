"""
Template for implementing electrical simulation backends in pylovo.

This module defines the abstract base class that all electrical simulation backends
must implement. It serves as a contract between pylovo's grid generation algorithms
and the underlying electrical simulation software.

Purpose within pylovo
---------------------
This template enables pylovo to support multiple electrical simulation engines
(pandapower, OpenDSS, etc.) without modifying the core grid generation logic.
Grid construction algorithms in cable_installer.py and grid_generator.py work with
high-level component specifications (BusSpec, LineSpec, etc.) rather than
backend-specific API calls.

Architecture Pattern
--------------------
- Grid generation algorithms create ComponentSpec objects (see component_specs.py)
- Backend implementations translate these specs to their native API calls
- This decoupling allows easy switching between simulation engines via config

Current Implementations
-----------------------
- PandapowerBackend: Production implementation using pandapower library
Contract Requirements
---------------------
Any backend implementation MUST:
1. Implement all @abstractmethod functions defined below
2. Accept ComponentSpec objects and translate to native API calls
3. Handle Pylovo grid conventions (400V, 20kV MV)
4. Support cable types from equipment_data table
5. Return consistent circuit metrics for analysis
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class IElectricalBackend(ABC):
    """
    Abstract backend template for electrical simulation engines.

    This class defines the required interface that all electrical backends must implement
    to be compatible with pylovo's grid generation system. See module docstring for
    detailed explanation of purpose and usage patterns.

    Implementation Guide
    --------------------
    1. Inherit from this class
    2. Implement all @abstractmethod functions
    3. Store backend-specific network object (e.g., pandapower.net, dss.circuit)
    4. Translate ComponentSpec objects to native API calls in create_component()
    5. Configure backend in config_generation.yaml under ELECTRICAL_BACKEND

    Example
    -------
    See src/electrical_backend/pandapower_backend.py for reference implementation.
    """

    @abstractmethod
    def initialize_circuit(self, name: str, source_bus: str,
                           primary_kv: float) -> None:
        """
        Initialize a new electrical circuit.

        Args:
            name: Circuit name
            source_bus: Name of the source bus
            primary_kv: Primary voltage level
        """

    @abstractmethod
    def create_component(self, spec: "ComponentSpec") -> Any:
        """
        Create electrical component from specification.

        Args:
            spec: Component specification object

        Returns:
            Backend-specific component object
        """

    @abstractmethod
    def solve_power_flow(self) -> bool:
        """
        Solve power flow and return convergence status.

        Returns:
            True if power flow converged, False otherwise
        """

    @abstractmethod
    def export_to_format(self) -> Dict[str, Any]:
        """
        Export circuit to configured format.

        Returns:
            Dictionary containing the exported circuit data
        """

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources and reset backend state."""

    @abstractmethod
    def get_circuit_metrics(self) -> Dict[str, Any]:
        """
        Get key circuit metrics after solving.

        Returns:
            Dictionary with circuit performance metrics
        """
