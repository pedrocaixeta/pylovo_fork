"""
Pandapower backend implementation for Pylovo

"""
import logging
from typing import Any, Dict, Optional

import pandapower as pp

from .backend_interface import IElectricalBackend
from .component_specs import BusSpec, ComponentSpec, LineSpec, LoadSpec, TransformerSpec, ExtGridSpec
from src.config_loader import V_BAND_HIGH, V_BAND_LOW


class PandapowerBackendError(Exception):
    """Exception raised by Pandapower backend operations."""


class PandapowerBackend(IElectricalBackend):
    """

    Manages pandapower network lifecycle and component creation.
    Designed to be a drop-in replacement for direct pp.create_*() calls.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.net = None
        self._circuit_name = None
        # Bus name to index mapping for faster lookups
        self._bus_cache: Dict[str, int] = {}

    def initialize_circuit(
        self, name: str, source_bus: str, primary_kv: float,
    ) -> None:
        """
        Initialize pandapower network with external grid.

        Args:
            name: Circuit name (e.g. "PLZ80331_kcid1_bcid2")
            source_bus: Name of MV source bus
            primary_kv: MV voltage level in kV (typically 20kV)
        """
        try:
            # Create empty pandapower network
            self.net = pp.create_empty_network(name=name)
            self._circuit_name = name
            self._bus_cache = {}

          
        except Exception as e:
            self.logger.error(f"Failed to initialize circuit: {e}")
            raise PandapowerBackendError(
                f"Circuit initialization failed: {e}"
            ) from e

    def create_component(self, spec: ComponentSpec) -> Any:
        """
        Create pandapower component from specification.

        Args:
            spec: Component specification (BusSpec, TransformerSpec, LineSpec, LoadSpec)

        Returns:
            Component index in pandapower network

        Raises:
            PandapowerBackendError: If component creation fails
        """
        if self.net is None:
            raise PandapowerBackendError(
                "Backend not initialized. Call initialize_circuit() first."
            )

        try:
            if isinstance(spec, BusSpec):
                return self._create_bus(spec)
            elif isinstance(spec, TransformerSpec):
                return self._create_transformer(spec)
            elif isinstance(spec, LineSpec):
                return self._create_line(spec)
            elif isinstance(spec, LoadSpec):
                return self._create_load(spec)
            elif isinstance(spec, ExtGridSpec):
                return self._create_ext_grid(spec)
            else:
                raise PandapowerBackendError(
                    f"Unknown component spec type: {type(spec).__name__}"
                )
        except Exception as e:
            self.logger.error(f"Failed to create component {spec.name}: {e}")
            raise PandapowerBackendError(
                f"Component creation failed: {e}"
            ) from e

    def _create_bus(self, spec: BusSpec) -> int:
        """Create bus from specification."""
        if spec.zone is not None:
            zone = spec.zone
        else:
            # TODO: What is the default here? 
            zone = "n"
        bus_idx = pp.create_bus(
            self.net,
            name=spec.name,
            vn_kv=spec.voltage_kv,
            geodata=spec.coordinates,
            max_vm_pu=V_BAND_HIGH,
            min_vm_pu=V_BAND_LOW,
            type="n",
            zone=zone
        )
        self._bus_cache[spec.name] = bus_idx
        self.logger.debug(f"Created bus: {spec.name} ({spec.voltage_kv}kV)")
        return bus_idx

    def _create_transformer(self, spec: TransformerSpec) -> int:
        """Create transformer from specification."""
        # Get bus indices
        mv_bus = self._get_bus_index(spec.bus1)
        lv_bus = self._get_bus_index(spec.bus2)

        # Use standard pandapower transformer type
        # Format: "sn_mva hv_kv/lv_kv" e.g. "0.63 MVA 20/0.4 kV"
        sn_mva = spec.kva / 1000.0
        std_type = f"{sn_mva} MVA 20/0.4 kV"

        trafo_idx = pp.create_transformer(
            self.net,
            hv_bus=mv_bus,
            lv_bus=lv_bus,
            std_type=std_type,
            name=spec.name,
            parallel=spec.parallel
        )

        self.logger.debug(f"Created transformer: {spec.name} ({spec.kva}kVA)")
        return trafo_idx

    def _create_line(self, spec: LineSpec) -> int:
        """Create line/cable from specification."""
        # Get bus indices
        from_bus = self._get_bus_index(spec.bus1)
        to_bus = self._get_bus_index(spec.bus2)

        # Use cable name as standard type (must be registered first)
        std_type = spec.cable_name if spec.cable_name else "NAYY 4x150 SE"

        line_idx = pp.create_line(
            self.net,
            from_bus=from_bus,
            to_bus=to_bus,
            length_km=spec.length_km,
            std_type=std_type,
            name=spec.name,
            geodata=spec.coordinates,
            parallel=spec.parallel
        )

        self.logger.debug(
            f"Created line: {spec.name} ({spec.length_km:.3f}km, {std_type})"
        )
        return line_idx

    def _create_load(self, spec: LoadSpec) -> int:
        """Create load from specification."""
        # Get bus index
        bus = self._get_bus_index(spec.bus)

        # Convert kW/kvar to MW/Mvar
        p_mw = spec.kw / 1000.0

        load_idx = pp.create_load(
            self.net,
            bus=bus,
            p_mw=p_mw,
            name=spec.name,
            max_p_mw=spec.max_p_mw
        )

        self.logger.debug(
            f"Created load: {spec.name} ({spec.kw:.1f}kW, {spec.kvar:.1f}kvar)"
        )
        return load_idx

    def _create_ext_grid(self, spec: ExtGridSpec) -> int:
        """Create external grid from specification."""
        bus = self._get_bus_index(spec.bus)
        ext_grid_idx = pp.create_ext_grid(self.net, bus=bus, vm_pu=spec.vm_pu, name=spec.name)
        return ext_grid_idx

    def _get_bus_index(self, bus_name: str) -> int:
        """
        Get bus index from name using cache.

        Args:
            bus_name: Bus name

        Returns:
            Bus index in pandapower network

        Raises:
            ValueError: If bus not found
        """
        if bus_name in self._bus_cache:
            return self._bus_cache[bus_name]

        # Fallback: search in dataframe
        buses = self.net.bus[self.net.bus.name == bus_name]
        if buses.empty:
            raise ValueError(f"Bus not found: {bus_name}")

        bus_idx = buses.index[0]
        self._bus_cache[bus_name] = bus_idx
        return bus_idx

    def register_cable_types(self, cables: list) -> None:
        """
        Register cable standard types from equipment data.

        Args:
            cables: List with cable specifications from database
        """
        # Create standard type for each cable in the database
        for cable in cables:
            name, r_ohm_per_km, x_ohm_per_km, max_i_ka = cable
            pp_name = name.replace('_', ' ')  # Extract name
            q_mm2 = int(name.split("_")[-1])  # Extract cross-section from name

            pp.create_std_type(self.net,
                {"r_ohm_per_km": float(r_ohm_per_km), "x_ohm_per_km": float(x_ohm_per_km), "max_i_ka": float(max_i_ka),
                    "c_nf_per_km": float(0),  # Set to zero for our standard grids
                    "q_mm2": q_mm2}, name=pp_name, element="line", )

        self.logger.debug(f"Created {len(cables)} standard cable types from equipment_data table")
        return None

    def solve_power_flow(self) -> bool:
        """
        Solve power flow using Newton-Raphson.

        Returns:
            True if converged, False otherwise
        """
        if self.net is None:
            raise PandapowerBackendError(
                "No network available for power flow analysis"
            )

        try:
            self.logger.debug("Solving power flow...")
            pp.runpp(self.net, algorithm='nr', init='auto')

            converged = self.net.converged
            if converged:
                self.logger.info("✓ Power flow converged")
            else:
                self.logger.warning("✗ Power flow did not converge")

            return converged

        except Exception as e:
            self.logger.error(f"Power flow failed: {e}")
            return False

    def export_to_format(self,filename: Optional[str] = None) -> str:
        """
        Export circuit to JSON format.

        Returns:
            JSON string representation of pandapower network
        """
        if self.net is None:
            raise PandapowerBackendError(
                "No network available for export"
            )

        try:
            json_str = pp.to_json(self.net, filename=filename)
            self.logger.info("✓ Exported to JSON")
            return json_str

        except Exception as e:
            self.logger.error(f"JSON export failed: {e}")
            raise PandapowerBackendError(
                f"JSON export failed: {e}"
            ) from e

    def cleanup(self) -> None:
        """Clean up network resources."""
        if self.net:
            self.net = None
            self._bus_cache = {}
            self.logger.debug("✓ Cleaned up network")

        self._circuit_name = None

    def get_circuit_metrics(self) -> Dict[str, Any]:
        """
        Get circuit metrics after power flow solution.

        Returns:
            Dictionary with network statistics and power flow results
        """
        if self.net is None:
            return {}

        metrics = {
            "name": self._circuit_name,
            "num_buses": len(self.net.bus),
            "num_lines": len(self.net.line),
            "num_transformers": len(self.net.trafo),
            "num_loads": len(self.net.load),
        }

        # Add convergence status
        if hasattr(self.net, 'converged'):
            metrics["converged"] = self.net.converged

        # Add voltage results if available
        if hasattr(self.net, 'res_bus') and not self.net.res_bus.empty:
            vm_pu = self.net.res_bus.vm_pu
            metrics["min_voltage_pu"] = float(vm_pu.min())
            metrics["max_voltage_pu"] = float(vm_pu.max())
            metrics["avg_voltage_pu"] = float(vm_pu.mean())

            # Check for voltage violations
            if metrics["min_voltage_pu"] < 0.95 or metrics["max_voltage_pu"] > 1.05:
                self.logger.warning(
                    f"Voltage violations: "
                    f"min={metrics['min_voltage_pu']:.3f}pu, "
                    f"max={metrics['max_voltage_pu']:.3f}pu"
                )

        # Add loss information
        if hasattr(self.net, 'res_line') and not self.net.res_line.empty:
            total_losses_mw = float(self.net.res_line.pl_mw.sum())
            metrics["total_losses_mw"] = total_losses_mw

        return metrics
