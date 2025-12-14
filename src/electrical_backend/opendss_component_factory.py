"""
OpenDSS Component Factory for pylovo.

This module provides a centralized factory class for creating all OpenDSS circuit components
directly on an OpenDSS instance using the pythonic interface. It focuses purely on component
creation and does not manage the OpenDSS instance lifecycle.

Adapted from pylovo-usa for German grid standards.

Key responsibilities:
- Bus creation and coordinate setting
- Transformer creation from equipment_data
- Line/cable creation with line codes
- Load creation (3-phase only)
- External grid/source creation
- Line code generation from equipment data
- Component tracking and summary reporting

Note:
- OpenDSS instance lifecycle (initialization, cleanup) is handled by OpenDSSBackend
- This factory assumes an already initialized OpenDSS instance
"""

import logging
from typing import Any

# Import equipment classes from equipment_adapters
# Separated to avoid circular imports with opendss_backend.py
from .equipment_adapters import CableEquipment, TransformerEquipment


class OpenDSSComponentFactory:
    """
    Factory class for creating OpenDSS components directly on an OpenDSS instance.

    This class centralizes all component creation logic and creates components
    directly on the provided OpenDSS instance using the pythonic interface.
    """

    def __init__(self, dss_instance: Any, logger: logging.Logger | None = None):
        """
        Initialize the OpenDSS component factory with an OpenDSS instance.

        Args:
            dss_instance: The OpenDSS instance to create components on
            logger: Optional logger for debugging
        """
        self.dss = dss_instance
        self.logger = logger or logging.getLogger(__name__)
        # Cache for created line code objects
        self.line_codes: dict[str, Any] = {}
        # Store bus voltage bases for tracking
        self._components_created: dict[str, list[Any]] = {
            "buses": [],
            "transformers": [],
            "lines": [],
            "loads": [],
            "sources": [],
            "linecodes": [],
            "capacitors": [],
            "meters": [],
        }

    # ===== COMPONENT CREATION UTILITIES =====

    # ===== TRANSFORMER CREATION =====

    def create_transformer_from_equipment(
        self,
        name: str,
        equipment: TransformerEquipment,
        bus1: str,
        bus2: str,
        conns: list[str],
    ) -> Any:
        """
        Create a transformer using equipment data.

        Args:
            name: Transformer name
            equipment: TransformerEquipment object from database
            bus1: Primary side bus
            bus2: Secondary side bus
            conns: Connection types

        Returns:
            Created transformer object
        """

        # Create transformer using pythonic interface
        xhl = equipment.reactance_pu * 100 if equipment.reactance_pu else 7.0

        transformer = self.dss.Transformer.new(
            name,
            Phases=equipment.n_phases,
            Windings=2,
            Buses=[bus1, bus2],
            Conns=conns,
            kVs=[equipment.primary_voltage_kv, equipment.secondary_voltage_kv],
            kVAs=[equipment.s_max_kva, equipment.s_max_kva],
            pctRs=[0.5, 0.5],
            XHL=xhl,
        )

        self._components_created["transformers"].append(transformer)
        self.logger.debug(f"Created transformer: {name} (kva={equipment.s_max_kva})")
        return transformer

    def create_mv_lv_transformer(self, name: str, equipment: TransformerEquipment, bus1: str, bus2: str) -> Any:
        """
        Create an MV-LV transformer (12.47kV -> 0.4kV).

        Args:
            name: Transformer name
            equipment: TransformerEquipment object
            bus1: MV side bus
            bus2: LV side bus

        Returns:
            Created transformer object
        """
        return self.create_transformer_from_equipment(name, equipment, bus1, bus2, conns=["delta", "wye"])

    def create_substation_transformer(self, name: str, equipment: TransformerEquipment, bus1: str, bus2: str) -> Any:
        """
        Create a substation transformer (69kV -> 20kV).

        Args:
            name: Transformer name
            equipment: TransformerEquipment object
            hv_bus: HV side bus
            mv_bus: MV side bus

        Returns:
            Created transformer object
        """
        return self.create_transformer_from_equipment(
            name,
            equipment,
            bus1,
            bus2,
            conns=["delta", "wye"],  # Typical for substation
        )

    # ===== LINE/CABLE CREATION =====

    def create_line_code(self, cable: CableEquipment) -> Any:
        """
        Create an OpenDSS line code from cable equipment data.

        Args:
            cable: CableEquipment object from database

        Returns:
            Created line code object (or existing if already created)
        """
        # Cable name is already normalized to underscore format (e.g., "NAYY_4_120")
        code_name = f"LC_{cable.name}"

        if code_name in self.line_codes:
            return self.line_codes[code_name]

        # Create line code using pythonic interface
        line_code = self.dss.LineCode.new(
            code_name,
            NPhases=cable.n_phases,
            R1=cable.r_ohm_per_km,
            X1=cable.x_ohm_per_km,
            R0=cable.r_ohm_per_km * 3,  # Zero sequence approximation
            X0=cable.x_ohm_per_km * 3,
            C1=0.0,  # Hardcoded to 0 (same as pandapower)
            C0=0.0,
            Units="km",
            NormAmps=cable.max_i_a,
            EmergAmps=cable.max_i_a * 1.25,
        )

        self.line_codes[code_name] = line_code
        self._components_created["linecodes"].append(line_code)
        self.logger.debug(f"Created line code: {code_name}")
        return line_code

    def create_line_from_equipment(
        self,
        name: str,
        cable: CableEquipment,
        bus1: str,
        bus2: str,
        length_km: float,
        units: str = "km",
    ) -> Any:
        """
        Create a line/cable using equipment data.

        Args:
            name: Line name
            cable: CableEquipment object from database
            bus1: From bus
            bus2: To bus
            length_km: Line length in kilometers
            units: Length units (default "km")

        Returns:
            Created line object
        """
        # First ensure line code exists
        line_code = self.create_line_code(cable)

        # Enforce minimum length to avoid zero-impedance (causes matrix inversion error)
        MIN_LENGTH_KM = 0.001  # 1 meter minimum
        if length_km < MIN_LENGTH_KM:
            self.logger.debug(f"Line {name}: length {length_km}km < {MIN_LENGTH_KM}km, using minimum")
            length_km = MIN_LENGTH_KM

        # Create line using pythonic interface
        line = self.dss.Line.new(
            name,
            Bus1=bus1,
            Bus2=bus2,
            LineCode=line_code,
            Length=length_km,
            Units=units,
            Phases=cable.n_phases,
        )

        self._components_created["lines"].append(line)
        self.logger.debug(f"Created line: {name} (length={length_km:.3f}km, type={cable.name})")
        return line

    # ===== LOAD CREATION =====

    def create_load(
        self,
        name: str,
        bus: str,
        kw: float,
        kvar: float,
        kv: float,
        n_phases: int = 3,
        conn: str = "wye",
        model: int = 1,
        pf: float | None = None,
    ) -> Any:
        """
        Create an OpenDSS load.

        Args:
            name: Load name
            bus: Bus to connect to
            kw: Active power in kW
            kvar: Reactive power in kvar (ignored if pf is specified)
            kv: Voltage in kV
            n_phases: Number of phases
            conn: Connection type ("wye" or "delta")
            model: Load model (1=constant PQ, 2=constant Z, 3=constant P)
            pf: Optional power factor (overrides kvar)

        Returns:
            Created load object
        """
        # Build load parameters
        load_params = {
            "Bus1": bus,
            "Phases": n_phases,
            "kV": kv,
            "kW": kw,
            "Conn": conn,
            "Model": model,
        }

        if pf is not None:
            load_params["pf"] = pf
        else:
            load_params["kvar"] = kvar

        # Create load using pythonic interface
        load = self.dss.Load.new(name, **load_params)

        self._components_created["loads"].append(load)
        self.logger.debug(f"Created load: {name} (kw={kw:.1f}, kvar={kvar:.1f})")
        return load

    def reset(self):
        """Reset the factory state for a new circuit."""
        self._components_created = {
            "buses": [],
            "transformers": [],
            "lines": [],
            "loads": [],
            "sources": [],
            "linecodes": [],
            "capacitors": [],
            "meters": [],
        }
        self.line_codes.clear()
        self.logger.info("Factory reset for new circuit")

