"""Electrical backend module for pylovo."""

from typing import Optional
from .backend_interface import IElectricalBackend
from .component_specs import BusSpec, ComponentSpec, LineSpec, LoadSpec, TransformerSpec
from .pandapower_backend import PandapowerBackend, PandapowerBackendError


def create_backend(backend_name: str = "pandapower", logger: Optional[object] = None) -> IElectricalBackend:
    """Factory function to create electrical backend instances.

    Args:
        backend_name: Name of the backend (e.g., "pandapower", "altdss")
        logger: Optional logger instance

    Returns:
        Backend instance implementing IElectricalBackend

    Raises:
        ValueError: If backend_name is not recognized
    """
    if backend_name in ("pandapower"):
        return PandapowerBackend(logger=logger)

    raise ValueError(f"Unknown backend: {backend_name}. Available: pandapower, pandapower_decoupled")


__all__ = [
    "IElectricalBackend",
    "ComponentSpec",
    "BusSpec",
    "TransformerSpec",
    "LineSpec",
    "LoadSpec",
    "PandapowerBackend",
    "PandapowerBackendError",
    "create_backend",
]
