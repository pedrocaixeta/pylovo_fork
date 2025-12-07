"""
Backend registry for electrical backends.

This module provides a lightweight registry that maps backend names to
callables constructing concrete backend instances.
"""

from typing import Callable, Dict, Iterable, Optional

from .template_backend import IElectricalBackend


BackendFactory = Callable[[Optional[object]], IElectricalBackend]


_REGISTRY: Dict[str, BackendFactory] = {}


def _normalize(name: str) -> str:
    """Normalize backend key for consistent lookups."""
    return name.strip().lower()


def register_backend(name: str, factory: BackendFactory) -> None:
    """
    Register a backend factory under the given name.

    Overwrites any existing entry for the normalized name.
    """
    _REGISTRY[_normalize(name)] = factory


def get_backend_factory(name: str) -> BackendFactory:
    """Get the factory for a backend by name or raise KeyError if missing."""
    key = _normalize(name)
    if key not in _REGISTRY:
        raise KeyError(name)
    return _REGISTRY[key]


def available_backends() -> Iterable[str]:
    """Return an iterable of available backend names (sorted)."""
    return tuple(sorted(_REGISTRY.keys()))


__all__ = [
    "BackendFactory",
    "register_backend",
    "get_backend_factory",
    "available_backends",
]


