"""
OpenDSS backend implementation for pylovo.

This module implements the IElectricalBackend interface using OpenDSS as the electrical
simulation engine. It handles OpenDSS instance lifecycle, component creation, and
provides a clean interface for grid construction algorithms.

Adapted from pylovo-usa for German grid standards (20kV/0.4kV, 3-phase).
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime
from typing import Any, Dict, Optional

from .template_backend import IElectricalBackend
from .component_specs import BusSpec, ComponentSpec, LineSpec, LoadSpec, TransformerSpec, ExtGridSpec
from .equipment_adapters import CableEquipment, TransformerEquipment

# Import Altdss with fallback
try:
    import altdss
except ImportError:
    altdss = None


class OpenDSSBackendError(Exception):
    """Exception raised by OpenDSS backend operations."""


class OpenDSSBackend(IElectricalBackend):
    """
    OpenDSS implementation of electrical backend interface.

    This backend uses OpenDSS for electrical simulation and provides German distribution
    standard settings (20kV/0.4kV, 3-phase). It manages the OpenDSS instance lifecycle and coordinates
    with the OpenDSSComponentFactory for component creation.
    """

    def __init__(self, logger: Optional[object] = None):
        """
        Initialize OpenDSS backend.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.dss = None
        self.component_factory = None
        self._circuit_name = None
        self.cable_registry: Dict[str, CableEquipment] = {}

        if altdss is None:
            raise OpenDSSBackendError("OpenDSS not available. Please install altdss package: pip install altdss")

    def initialize_circuit(self, name: str, source_bus: str, primary_kv: float) -> None:
        """
        Initialize OpenDSS circuit with German distribution standards.

        Args:
            name: Circuit name
            source_bus: Name of the source bus
            primary_kv: Primary voltage level (typically 20kV for German MV)
        """
        try:
            altdss.altdss("Clear")
            altdss.altdss(f"New Circuit.{name} basekv={primary_kv} pu=1.0 phases=3 bus1={source_bus}")

            # Set German distribution voltage bases
            voltage_bases = [
                primary_kv,  # MV level (typically 20kV)
                20.0,  # Standard German MV
                0.4,   # Standard German LV (400V L-L)
            ]
            bases_str = ",".join(str(v) for v in voltage_bases)
            altdss.altdss(f"Set VoltageBases=[{bases_str}]")

            altdss.altdss("CalcVoltageBases")

            altdss.altdss("Set DefaultBaseFrequency=50")

            self.dss = altdss.altdss
            self._circuit_name = name

            # Initialize component factory (lazy import to avoid circular dependency)
            from .opendss_component_factory import OpenDSSComponentFactory
            self.component_factory = OpenDSSComponentFactory(self.dss, self.logger)

            # Edit the existing Vsource (created by initialize_circuit) to set MVA levels
            self.dss(
                f"Edit Vsource.source basekv={primary_kv} pu=1.0 phases=3 bus1={source_bus} " f"MVASC3=1000 MVASC1=900"
            )
            self.logger.info(f"✓ Initialized OpenDSS circuit: {name}")
            self.logger.debug(f"Voltage bases: {voltage_bases} kV")

        except Exception as e:
            self.logger.error(f"Failed to initialize OpenDSS circuit: {str(e)}")
            raise OpenDSSBackendError(
                f"OpenDSS initialization failed: {
                    str(e)}"
            ) from e

    def register_cable_types(self, cables: list) -> None:
        """Register cable types from database tuples."""
        for cable_tuple in cables:
            name, r_ohm, x_ohm, max_i = cable_tuple
            # Convert tuple to equipment object
            cable_obj = CableEquipment(
                name=name,
                r_ohm_per_km=r_ohm,
                x_ohm_per_km=x_ohm,
                max_i_ka=max_i
            )

            # Store in registry with canonical name
            from .component_specs import normalize_cable_name
            canonical = normalize_cable_name(name)
            self.cable_registry[canonical] = cable_obj
            # Also keep original for backwards compatibility
            if name != canonical:
                self.cable_registry[name] = cable_obj

            # Create line code in OpenDSS when factory is available
            if self.component_factory:
                self.component_factory.create_line_code(cable_obj)

        self.logger.info(f"Registered {len(cables)} cable types")

    def _get_bus_index(self, bus_name: str) -> str:
        """
        Return bus identifier for OpenDSS.

        Note: OpenDSS uses string names, not integer indices like pandapower.
        This method exists for API compatibility with pandapower backend.

        Args:
            bus_name: Bus name

        Returns:
            Bus name (OpenDSS uses names directly, not indices)
        """
        return bus_name

    def _find_fallback_cable(self, cable_name: str) -> CableEquipment | None:
        """
        Find a fallback cable when the requested cable is not available.

        Tries to find a cable of the same type (NAYY/NYY) with the closest
        higher capacity (larger cross-section).

        Args:
            cable_name: Requested cable name (e.g., "NAYY_4_150")

        Returns:
            CableEquipment object if fallback found, None otherwise
        """
        # Extract cable type (NAYY or NYY) from name
        cable_type = None
        for prefix in ["NAYY", "NYY"]:
            if prefix in cable_name.upper():
                cable_type = prefix
                break

        if not cable_type:
            return None

        # Find all cables of same type, sorted by capacity (max_i_a)
        same_type_cables = [
            (name, cable)
            for name, cable in self.cable_registry.items()
            if cable_type in name.upper() and "kV" not in name
        ]

        if not same_type_cables:
            return None

        # Sort by capacity (max_i_a) and return the highest capacity cable
        same_type_cables.sort(key=lambda x: x[1].max_i_a, reverse=True)
        return same_type_cables[0][1]

    def create_component(self, spec: ComponentSpec) -> Any:
        """
        Create OpenDSS component from specification for German 3-phase grids.

        Args:
            spec: Component specification object

        Returns:
            OpenDSS component object or index
        """
        if self.component_factory is None:
            raise OpenDSSBackendError("Backend not initialized. Call initialize_circuit() first.")

        try:
            if isinstance(spec, TransformerSpec):
                # German grids only use 3-phase MV-LV transformers
                equipment = TransformerEquipment(
                    name=spec.name,
                    s_max_kva=spec.kva,
                    primary_voltage_kv=20.0,  # German MV
                    secondary_voltage_kv=0.4   # German LV
                )
                return self.component_factory.create_mv_lv_transformer(
                    name=spec.name,
                    equipment=equipment,
                    bus1=spec.bus1,
                    bus2=spec.bus2,
                )

            elif isinstance(spec, LineSpec):
                # Convert cable_name to cable_equipment
                cable_equipment = self.cable_registry.get(spec.cable_name)
                if not cable_equipment:
                    # Try fallback: find a similar cable with higher capacity
                    cable_equipment = self._find_fallback_cable(spec.cable_name)
                    if cable_equipment:
                        self.logger.warning(f"Cable '{spec.cable_name}' not found, using fallback '{cable_equipment.name}'")
                    else:
                        available = list(self.cable_registry.keys())[:10]
                        raise OpenDSSBackendError(
                            f"Cable type '{spec.cable_name}' not registered. "
                            f"Available: {available}... Call register_cable_types first."
                        )

                # German grids use 3-phase lines only
                return self.component_factory.create_line_from_equipment(
                    name=spec.name,
                    cable=cable_equipment,
                    bus1=spec.bus1,
                    bus2=spec.bus2,
                    length_km=spec.length_km,
                )

            elif isinstance(spec, LoadSpec):
                # German grids use 3-phase balanced loads
                return self.component_factory.create_load(
                    name=spec.name,
                    bus=spec.bus,
                    kw=spec.kw,
                    kvar=spec.kvar,
                    kv=0.4,  # German LV
                    n_phases=3,
                    conn="wye"
                )

            elif isinstance(spec, BusSpec):
                # OpenDSS creates buses implicitly
                return spec.name

            elif isinstance(spec, ExtGridSpec):
                # External grid is created in initialize_circuit
                return "source"

            else:
                raise OpenDSSBackendError(f"Unknown component spec type: {type(spec)}")

        except Exception as e:
            self.logger.error(
                f"Failed to create component {
                    spec.name}: {
                    str(e)}"
            )
            raise OpenDSSBackendError(
                f"Component creation failed: {
                    str(e)}"
            ) from e

    def solve_power_flow(self) -> bool:
        """Solve power flow and return convergence status."""
        if self.dss is None:
            raise OpenDSSBackendError("No OpenDSS instance available for analysis")

        try:
            # CRITICAL: Calculate voltage bases before solving
            # This assigns proper kVBase to all buses based on connectivity
            self.logger.info("Calculating voltage bases...")
            self.dss("CalcVoltageBases")

            self.logger.debug("Solving power flow...")
            self.dss.Solution.Solve()

            converged = self.dss.Solution.Converged
            if converged:
                self.logger.info("✓ Power flow converged")
            else:
                self.logger.error("✗ Power flow did not converge")

            try:
                report_filename = (
                    f"{self._circuit_name}_electrical_statistics.txt"
                    if self._circuit_name
                    else "electrical_statistics.txt"
                )
                self.generate_electrical_statistics_report(report_filename)
            except Exception as diag_err:
                self.logger.warning(f"Electrical statistics report generation failed: {str(diag_err)}")

            return converged

        except Exception as e:
            self.logger.error(f"Power flow solution failed: {str(e)}")
            return False

    def generate_electrical_statistics_report(self, output_filename: str = "electrical_statistics.txt") -> None:
        """Generate electrical statistics report after power flow solve."""
        if self.dss is None:
            return

        circuit_name = self._circuit_name or "unknown"
        m = re.search(r"K\d+_S\d+", circuit_name or "")
        subfolder = m.group(0) if m else circuit_name
        stats_dir = os.path.abspath(os.path.join(os.getcwd(), "statistics", subfolder))
        os.makedirs(stats_dir, exist_ok=True)
        out_path = os.path.join(stats_dir, output_filename)
        out_dir = stats_dir
        converged = bool(self.dss.Solution.Converged)
        total_power = self.dss.TotalPower()
        total_losses = self.dss.Losses()
        try:
            raw_bus_names = self.dss.BusNames()
            bus_names = list(raw_bus_names) if raw_bus_names is not None else []
        except Exception:
            bus_names = []
        try:
            raw_bus_vmags = self.dss.BusVMagPU()
            bus_vmags = list(raw_bus_vmags) if raw_bus_vmags is not None else []
        except Exception:
            bus_vmags = []

        min_v = min(bus_vmags) if bus_vmags else None
        max_v = max(bus_vmags) if bus_vmags else None
        avg_v = (sum(bus_vmags) / len(bus_vmags)) if bus_vmags else None
        zero_voltage_buses: list[str] = []
        for name, vpu in zip(bus_names, bus_vmags, strict=False):
            try:
                if abs(float(vpu)) < 1e-8:
                    zero_voltage_buses.append(name)
            except Exception:
                continue

        # Export CSVs; then move/copy from repo root into statistics/<circuit>
        export_types = ["Voltages", "Currents", "Powers", "Losses", "Loads"]
        exported_files = []

        for export_type in export_types:
            try:
                self.dss(f"Export {export_type}")

                base_name = f"{export_type}.csv"
                root_base = os.path.join(os.getcwd(), base_name)
                stats_base = os.path.join(stats_dir, base_name)
                tagged_name = f"{circuit_name}_EXP_{export_type.upper()}.csv"
                stats_tagged = os.path.join(stats_dir, tagged_name)

                if os.path.exists(root_base):
                    # Move the root export into statistics as tagged file
                    shutil.move(root_base, stats_tagged)
                elif os.path.exists(stats_base):
                    # DSS may have written directly into stats_dir; create tagged copy
                    shutil.copy2(stats_base, stats_tagged)
                else:
                    # Nothing found; skip
                    continue

                exported_files.append(stats_tagged)
                self.logger.debug(f"✓ Exported {export_type} → {stats_tagged}")
            except Exception as e:
                self.logger.warning(f"Failed to export {export_type}: {str(e)}")
                continue

        json_snapshot_path = None
        try:
            json_str = self.dss.to_json()
            json_basename = (
                f"circuit_snapshot_{self._circuit_name}.json" if self._circuit_name else "circuit_snapshot.json"
            )
            json_snapshot_path = os.path.abspath(os.path.join(out_dir, json_basename))
            with open(json_snapshot_path, "w") as f:
                json.dump(json.loads(json_str), f, indent=2)
        except Exception:
            pass

        def _to_kw(value: Any) -> float | None:
            try:
                if hasattr(value, "real"):
                    return float(value.real)
                if isinstance(value, (list, tuple)) and len(value) > 0:
                    return float(value[0])
                return float(value)
            except Exception:
                return None

        with open(out_path, "w") as f:
            f.write("=" * 80 + "\n")
            f.write("Electrical Statistics Report\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")
            f.write(f"Circuit: {self._circuit_name or 'unknown'}\n")
            f.write(f"Converged: {converged}\n")
            tp_kw = _to_kw(total_power)
            tl_w = _to_kw(total_losses)
            tl_kw = (tl_w / 1000.0) if tl_w is not None else None
            if tp_kw is not None:
                f.write(f"Total Power kW: {tp_kw:.3f}\n")
            if tl_kw is not None:
                f.write(f"Total Losses kW: {tl_kw:.3f}\n")

            f.write("\nVoltage stats (pu):\n")
            f.write(f"  min: {min_v if min_v is not None else 'n/a'}\n")
            f.write(f"  avg: {avg_v if avg_v is not None else 'n/a'}\n")
            f.write(f"  max: {max_v if max_v is not None else 'n/a'}\n")

            if zero_voltage_buses:
                f.write(f"\nZero-voltage buses ({len(zero_voltage_buses)}):\n")
                # cap list to avoid huge files
                preview = zero_voltage_buses[:200]
                for b in preview:
                    f.write(f"  - {b}\n")
                if len(zero_voltage_buses) > len(preview):
                    f.write(f"  ... and {len(zero_voltage_buses) - len(preview)} more\n")
            else:
                f.write("\nZero-voltage buses: none\n")

            f.write("\nExported files:\n")
            for p in exported_files:
                f.write(f"  - {p}\n")

            if json_snapshot_path:
                f.write(f"\nJSON snapshot: {json_snapshot_path}\n")

    def export_to_format(self, filename: Optional[str] = None) -> str:
        """
        Export circuit to JSON format.

        Args:
            filename: If provided, save to this file path. If None, return JSON string only.

        Returns:
            JSON string representation of the circuit
        """
        if self.dss is None:
            raise OpenDSSBackendError("No OpenDSS instance available for export")

        try:
            # Export using OpenDSS built-in JSON functionality
            json_str = self.dss.to_json()

            # Write to file if filename provided
            if filename:
                with open(filename, 'w') as f:
                    f.write(json_str)
                self.logger.info(f"✓ Exported circuit to JSON file: {filename}")
            else:
                self.logger.info("✓ Exported circuit to JSON format")

            return json_str

        except Exception as e:
            self.logger.error(f"JSON export failed: {str(e)}")
            raise OpenDSSBackendError(f"JSON export failed: {str(e)}") from e

    def cleanup(self) -> None:
        """Clean up OpenDSS resources and reset state."""
        if self.dss:
            try:
                self.dss("Clear")
                self.logger.debug("✓ Cleared OpenDSS circuit")
            except Exception as e:
                self.logger.warning(f"Error clearing OpenDSS circuit: {str(e)}")
            finally:
                self.dss = None

        if self.component_factory:
            try:
                self.component_factory.reset()
                self.logger.debug("✓ Reset component factory")
            except Exception as e:
                self.logger.warning(
                    f"Error resetting component factory: {
                        str(e)}"
                )
            finally:
                self.component_factory = None

        # Clear internal state
        self._circuit_name = None

        self.logger.debug("✓ OpenDSS cleanup completed")

    def get_circuit_metrics(self) -> dict[str, Any]:
        """Get key circuit metrics after solving."""
        if self.dss is None:
            return {}

        try:
            # Get total power and losses
            total_power = self.dss.TotalPower()
            total_losses = self.dss.Losses()

            metrics = {
                "converged": self.dss.Solution.Converged,
                "total_power_kw": total_power.real if total_power else 0,
                "total_losses_kw": total_losses.real / 1000 if total_losses else 0,
                "num_buses": self.dss.NumBuses,
                "num_elements": self.dss.NumCircuitElements,
            }

            # Get voltage statistics
            bus_voltages = self.dss.BusVMagPU()
            if bus_voltages is not None and len(bus_voltages) > 0:
                metrics["min_voltage_pu"] = min(bus_voltages)
                metrics["max_voltage_pu"] = max(bus_voltages)
                metrics["avg_voltage_pu"] = sum(bus_voltages) / len(bus_voltages)

                # Log voltage validation info
                min_v, max_v, avg_v = (
                    metrics["min_voltage_pu"],
                    metrics["max_voltage_pu"],
                    metrics["avg_voltage_pu"],
                )
                self.logger.info(
                    f"Voltage range: {
                        min_v:.3f} - {
                        max_v:.3f} pu (avg: {
                        avg_v:.3f})"
                )

                if min_v < 0.95 or max_v > 1.05:
                    self.logger.warning(
                        f"Voltage violations detected: min={
                            min_v:.3f}pu, max={
                            max_v:.3f}pu"
                    )

            return metrics

        except Exception as e:
            self.logger.warning(f"Error getting circuit metrics: {str(e)}")
            return {}

    # =========================================================================
    # Query Methods - Read data from backend
    # =========================================================================

    def get_cable_types(self) -> list[str]:
        """
        Get all registered cable type names.

        Returns:
            List of cable type names available in the registry
        """
        return list(self.cable_registry.keys())

    def get_component_count(self, component_type: str) -> int:
        """
        Get component count by type.

        Args:
            component_type: One of 'buses', 'lines', 'loads', 'transformers'

        Returns:
            Number of components of the specified type
        """
        if self.component_factory is None:
            return 0
        components = self.component_factory._components_created
        return len(components.get(component_type, []))

    def get_bus_coordinates(self, bus_name: str) -> tuple[float, float] | None:
        """
        Get bus geographic coordinates.

        OpenDSS does not store geodata; visualization uses database coordinates.

        Args:
            bus_name: Name of the bus

        Returns:
            None (OpenDSS doesn't store geodata)
        """
        return None

    # =========================================================================
    # Update Methods - Modify existing components (no-ops for OpenDSS)
    # =========================================================================

    def set_bus_coordinates(self, bus_name: str, x: float, y: float) -> None:
        """
        Set bus geographic coordinates.

        No-op for OpenDSS - visualization handled via database geodata.

        Args:
            bus_name: Name of the bus
            x: X coordinate
            y: Y coordinate
        """
        pass

    def set_bus_zone(self, bus_name: str, zone: str) -> None:
        """
        Set bus zone attribute.

        No-op for OpenDSS - zone concept not used.

        Args:
            bus_name: Name of the bus
            zone: Zone identifier string
        """
        pass

    def set_transformer_rating(self, trafo_name: str, rating_mva: float) -> None:
        """
        Set transformer rated power.

        No-op for OpenDSS - transformers are sized at creation.

        Args:
            trafo_name: Name of the transformer
            rating_mva: Rated power in MVA
        """
        pass
