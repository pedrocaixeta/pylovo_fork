"""
Component specification classes for German 3-phase LV grids.

MINIMAL VERSION - Simplified for pylovo German distribution grids:
- All grids are 3-phase balanced (no n_phases field)
- Standard voltages: 20kV (MV), 0.4kV (LV)
- No equipment schema dependencies
- Only essential attributes needed for pandapower

Design principles:
- ComponentSpecs are pure data - no logic, no equipment objects
- Transformers: only need kVA rating (not full equipment data)
- Cables: only need cable_name (looked up in database)
- Buses: only need voltage and coordinates
- Loads: only need kW, kvar
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ComponentSpec:
    """Base class for all component specifications."""
    name: str
    component_type: str = ""


@dataclass
class BusSpec(ComponentSpec):
    """
    Bus specification for German 3-phase grids.

    Standard voltages:
    - 20kV for MV buses
    - 0.4kV for LV buses
    """
    voltage_kv: float = 0.4  # Nominal voltage in kV
    coordinates: Optional[Tuple[float, float]] = None  # (lon, lat) for visualization
    zone: Optional[str] = None  # Zone for load type tracking

    def __post_init__(self):
        self.component_type = "bus"


@dataclass
class TransformerSpec(ComponentSpec):
    """
    Transformer specification for MV/LV transformers.

    All transformers are 3-phase, 20kV/0.4kV.
    Ratings determined by grid generation algorithm.
    """
    bus1: str = ""  # Primary (MV) side bus name
    bus2: str = ""  # Secondary (LV) side bus name
    kva: float = 630.0  # Rated apparent power in kVA
    parallel: int = 1  # Number of parallel transformers

    def __post_init__(self):
        self.component_type = "transformer"


@dataclass
class LineSpec(ComponentSpec):
    """
    Line/Cable specification for distribution cables.

    All cables are 3-phase, underground NAYY cables.
    Cable type name references equipment_data table.
    """
    bus1: str = ""  # From bus name
    bus2: str = ""  # To bus name
    cable_name: str = ""  # Cable type from equipment_data (e.g. "NAYY 4x150 SE")
    length_km: float = 0.0  # Cable length in km
    parallel: int = 1  # Number of parallel cables
    coordinates: Optional[list] = None  # Line geometry for visualization
    

    def __post_init__(self):
        self.component_type = "line"


@dataclass
class LoadSpec(ComponentSpec):
    """
    Load specification for household/building loads.

    All loads are 3-phase balanced.
    """
    bus: str = ""  # Bus name where load is connected
    kw: float = 0.0  # Active power in kW
    kvar: float = 0.0  # Reactive power in kvar
    max_p_mw: float = 0.0  # Maximum active power in MW

    def __post_init__(self):
        self.component_type = "load"

class ExtGridSpec(ComponentSpec):
    """External grid specification."""

    bus: str = ""
    vm_pu: float = 1.0

    def __post_init__(self):
        self.component_type = "ext_grid"
