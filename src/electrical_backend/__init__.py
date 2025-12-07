"""Electrical backend package public API for pylovo."""

from typing import Optional

from .template_backend import IElectricalBackend
from .component_specs import (
    BusSpec,
    ComponentSpec,
    LineSpec,
    LoadSpec,
    TransformerSpec,
)
from .factory import create_backend
from .registry import available_backends, register_backend


def __getattr__(name: str):
    """
    Lazy access for optional heavy symbols to keep import time low while
    preserving the public API.
    """
    if name in {"PandapowerBackend", "PandapowerBackendError"}:
        from .pandapower_backend import PandapowerBackend, PandapowerBackendError

        return {
            "PandapowerBackend": PandapowerBackend,
            "PandapowerBackendError": PandapowerBackendError,
        }[name]
    raise AttributeError(f"module 'electrical_backend' has no attribute {name!r}")


__all__ = [
    "IElectricalBackend",
    "ComponentSpec",
    "BusSpec",
    "TransformerSpec",
    "LineSpec",
    "LoadSpec",
    "create_backend",
    "register_backend",
    "available_backends",
    "PandapowerBackend",
    "PandapowerBackendError",
]
