"""
Factory utilities for creating electrical backends.

Backends are looked up via the local registry and instantiated lazily to
avoid importing heavy dependencies during package import time.
"""

from typing import Optional

from .template_backend import IElectricalBackend
from .registry import (
    available_backends,
    get_backend_factory,
    register_backend,
)


def _pandapower_ctor(logger: Optional[object]) -> IElectricalBackend:
    # Lazy import to avoid importing pandapower unless needed
    from .pandapower_backend import PandapowerBackend

    return PandapowerBackend(logger=logger)


# Register built-in backends on module import (still lazy per-backend)
register_backend("pandapower", _pandapower_ctor)


def create_backend(
    backend_name: str = "pandapower", logger: Optional[object] = None
) -> IElectricalBackend:
    """Create a backend instance by name.

    Raises ValueError with a friendly message if the backend is unknown.
    """
    try:
        factory = get_backend_factory(backend_name)
    except KeyError:
        raise ValueError(
            f"Unknown backend: {backend_name}. Available: {', '.join(available_backends())}"
        )
    return factory(logger)


__all__ = ["create_backend"]


