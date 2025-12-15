"""Cable installation module for electrical grid generation."""

import numpy as np
import pandas as pd
from src.electrical_backend.template_backend import IElectricalBackend
from src.electrical_backend.component_specs import BusSpec, TransformerSpec, LineSpec, LoadSpec, ExtGridSpec
from src.config_loader import VN, V_BAND_LOW, VOLTAGE_DROP_SMALL_LOAD_PERCENT_PER_KM, VOLTAGE_DROP_LARGE_LOAD_PERCENT_PER_KM, SMALL_LOAD_THRESHOLD_KW, VOLTAGE_DROP_DISTRIBUTION_PERCENT, DEFAULT_POWER_FACTOR
from src.utils import oneSimultaneousLoad


class CableInstaller:
    """Handles cable installation for electrical grids using backend abstraction."""

    def __init__(self, backend: IElectricalBackend, dbc, logger, cables: list):
        """Initialize cable installer.

        Args:
            backend: Electrical backend instance (e.g., PandapowerBackend)
            dbc: Database client for accessing grid data
            logger: Logger instance
            cables: List of cable tuples from database (name, r_ohm_per_km, x_ohm_per_km, max_i_ka)
        """
        self.backend = backend
        self.dbc = dbc
        self.logger = logger

        # Cache cable data from database as DataFrame (single source of truth)
        self._cable_df = self._build_cable_dataframe(cables)

    @staticmethod
    def _build_cable_dataframe(cables: list) -> pd.DataFrame:
        """Build cable DataFrame from database tuples.

        Normalizes cable names to underscore format (e.g., "NAYY_4_120")
        which is compatible with both pandapower and OpenDSS backends.

        Args:
            cables: List of tuples (name, r_ohm_per_km, x_ohm_per_km, max_i_ka)

        Returns:
            DataFrame indexed by normalized cable name with electrical properties
        """
        from src.electrical_backend.component_specs import normalize_cable_name
        cable_data = {}
        for name, r_ohm, x_ohm, max_i_ka in cables:
            normalized_name = normalize_cable_name(name)

            try:
                q_mm2 = int(name.split("_")[-1])
            except (ValueError, IndexError):
                q_mm2 = 0

            cable_data[normalized_name] = {
                'r_ohm_per_km': float(r_ohm),
                'x_ohm_per_km': float(x_ohm),
                'max_i_ka': float(max_i_ka),
                'q_mm2': q_mm2
            }

        return pd.DataFrame.from_dict(cable_data, orient="index")

    def create_lvmv_bus(self, plz: int, kcid: int, bcid: int) -> None:
        """Create LV and MV buses."""
        lv_geodata = self.dbc.get_ont_geom_from_bcid(plz, kcid, bcid)
        lv_bus_spec = BusSpec(
            name="LVbus 1",
            voltage_kv=VN * 1e-3,
            coordinates=lv_geodata
        )
        mv_geodata = (float(lv_geodata[0]), float(lv_geodata[1]) + 1.5 * 1e-4)
        mv_bus_spec = BusSpec(
            name="MVbus 1",
            voltage_kv=20.0,
            coordinates=mv_geodata
        )
        self.backend.create_component(lv_bus_spec)
        self.backend.create_component(mv_bus_spec)

        self.backend.create_component(ExtGridSpec(name="External grid", bus="MVbus 1", vm_pu=1))

        # Add busbar line between MV and LV buses 
        busbar_line_spec = LineSpec(
            name="MV-LV Busbar",
            bus1="MVbus 1",
            bus2="LVbus 1",
            cable_name="NAYY_4_185",
            length_km=0.001,
            parallel=1,
            coordinates=[mv_geodata, lv_geodata]
        )
        self.backend.create_component(busbar_line_spec)

    def create_transformer(self, plz: int, kcid: int, bcid: int) -> None:
        """
        Create a transformer based on the required rated power.

        Maps the required capacity to either a single standard transformer
        or a parallel configuration (2x) for specific larger loads.
        """
        transformer_rated_power = self.dbc.get_transformer_rated_power_from_bcid(plz, kcid, bcid)

        if transformer_rated_power in (100, 160, 250, 400, 630):
            trafo_name = f"{str(transformer_rated_power)} transformer"
            kva = transformer_rated_power
            parallel = 1
        elif transformer_rated_power in (500, 800, 1260):
            trafo_name = f"double {str(transformer_rated_power * 0.5)} transformer"
            kva = transformer_rated_power * 0.5
            parallel = 2
        else:
            # Fallback: use 630 kVA transformers in parallel for large parallel transormers
            trafo_name = "multiple 630 transformer"
            kva = 630
            parallel = max(1, int(transformer_rated_power / 630))

        trafo_spec = TransformerSpec(
            name=trafo_name,
            bus1="MVbus 1",
            bus2="LVbus 1",
            kva=kva,
            parallel=parallel
        )

        self.backend.create_component(trafo_spec)
        self.backend.set_transformer_rating(trafo_spec.name, transformer_rated_power * 1e-3)

    def create_connection_bus(self, connection_nodes: list):
        """Create connection buses."""
        for node in connection_nodes:
            node_geodata = self.dbc.get_node_geom(node)
            bus_spec = BusSpec(
                name=f"Connection Nodebus {node}",
                voltage_kv=VN * 1e-3,
                coordinates=node_geodata,
            )
            self.backend.create_component(bus_spec)

    def create_consumer_bus_and_load(self, consumer_list: list, load_units: dict,
                                     load_type: dict, building_df: pd.DataFrame,
                                     consumer_categories: pd.DataFrame) -> None:
        """Create consumer buses and loads with simultaneity-adjusted power.

        Applies Kerber formula per building to calculate simultaneous load.
        """

        for consumer in consumer_list:
            node_geodata = self.dbc.get_node_geom(consumer)
            ltype = load_type[consumer]

            # Get peak load per household
            if ltype in ["SFH", "MFH", "AB", "TH"]:
                peak_load = consumer_categories.loc[
                    consumer_categories["definition"] == ltype, "peak_load"
                ].values[0]
            else:
                peak_load = building_df[building_df["vertice_id"] == consumer]["peak_load_in_kw"].tolist()[0]

            # Get simultaneity factor for this building type
            sim_factor_row = consumer_categories.loc[
                consumer_categories["definition"] == ltype, "sim_factor"
            ]
            sim_factor = sim_factor_row.values[0] if len(sim_factor_row) > 0 else 0.07

            # Calculate simultaneous load using Kerber formula (per building)
            num_households = load_units[consumer]
            total_installed_kw = peak_load * num_households
            simultaneous_load_kw = oneSimultaneousLoad(total_installed_kw, num_households, sim_factor)

            # Calculate reactive power from power factor
            phi = np.arccos(DEFAULT_POWER_FACTOR)
            kvar = simultaneous_load_kw * np.tan(phi)

            # Create bus
            bus_spec = BusSpec(
                name=f"Consumer Nodebus {consumer}",
                voltage_kv=VN * 1e-3,
                coordinates=node_geodata,
                zone=ltype
            )
            self.backend.create_component(bus_spec)
            self.backend.set_bus_zone(bus_spec.name, ltype)

            # Create one aggregated load per building with simultaneous load
            load_spec = LoadSpec(
                name=f"Load {consumer}",
                bus=f"Consumer Nodebus {consumer}",
                kw=simultaneous_load_kw,
                kvar=kvar,
                max_p_mw=total_installed_kw * 1e-3,
            )
            self.backend.create_component(load_spec)

    def install_consumer_cables(self, plz: int, bcid: int, kcid: int,
                                branch_deviation: float, branch_node_list: list,
                                ont_vertice: int, vertices_dict: dict, Pd: dict,
                                connection_available_cables: list[str],
                                local_length_dict: dict) -> dict:
        """Install consumer connection cables."""
        # Normalize cable names from config to match internal format
        from src.electrical_backend.component_specs import normalize_cable_name
        connection_available_cables = [normalize_cable_name(c) for c in connection_available_cables]

        consumer_list = self.dbc.get_vertices_from_connection_points(branch_node_list)
        branch_consumer_list = [n for n in consumer_list if n in vertices_dict.keys()]

        for vertice in branch_consumer_list:
            path_list = self.dbc.get_path_to_bus(vertice, ont_vertice)
            start_vid = path_list[1]
            end_vid = path_list[0]

            geodata = self.dbc.get_node_geom(start_vid)
            start_node_geodata = (float(geodata[0]) + 5 * 1e-6 * branch_deviation,
                                  float(geodata[1]) + 5 * 1e-6 * branch_deviation)
            end_node_geodata = self.dbc.get_node_geom(end_vid)
            line_geodata = [start_node_geodata, end_node_geodata]

            length_km = (vertices_dict[end_vid] - vertices_dict[start_vid]) * 1e-3
            count = 1
            sim_load = Pd[end_vid]
            Imax = sim_load * 1e-3 / (VN * V_BAND_LOW * np.sqrt(3))

            voltage_available_cables_df = None
            line_df = self._cable_df
            while True:
                current_available_cables_df = line_df[
                    (line_df["max_i_ka"] >= Imax / count) & (line_df.index.isin(connection_available_cables))
                ]

                if len(current_available_cables_df) == 0:
                    count += 1
                    continue

                current_available_cables_df["cable_impedence"] = np.sqrt(
                    current_available_cables_df["r_ohm_per_km"] ** 2 +
                    current_available_cables_df["x_ohm_per_km"] ** 2
                )

                if sim_load <= SMALL_LOAD_THRESHOLD_KW:
                    voltage_drop_limit = VN * VOLTAGE_DROP_SMALL_LOAD_PERCENT_PER_KM / 100
                else:
                    voltage_drop_limit = VN * VOLTAGE_DROP_LARGE_LOAD_PERCENT_PER_KM / 100

                voltage_available_cables_df = current_available_cables_df[
                    current_available_cables_df["cable_impedence"] <=
                    voltage_drop_limit / (Imax * length_km / count)
                ]

                if len(voltage_available_cables_df) == 0:
                    count += 1
                    continue
                else:
                    break

            cable = voltage_available_cables_df.sort_values(by=["q_mm2"]).index.tolist()[0]
            local_length_dict[cable] += count * length_km

            line_spec = LineSpec(
                name=f"Line to {end_vid}",
                bus1=f"Connection Nodebus {start_vid}",
                bus2=f"Consumer Nodebus {end_vid}",
                cable_name=cable,
                length_km=length_km,
                parallel=count,
                coordinates=line_geodata,
            )
            self.backend.create_component(line_spec)

            line_name = f"L{end_vid}"[:15]
            self.dbc.insert_lines(
                geom=line_geodata, plz=plz, bcid=bcid, kcid=kcid, line_name=line_name,
                std_type=cable,
                from_bus=start_vid,
                to_bus=end_vid,
                length_km=length_km
            )

        return local_length_dict

    def find_minimal_available_cable(self, Imax: float, distance: int = 0) -> tuple[str, int]:
        """Find the smallest cable that meets requirements."""
        count = 1
        cable = None
        line_df = self._cable_df

        while True:
            current_available_cables = line_df[(line_df["max_i_ka"] >= Imax / count)]

            if len(current_available_cables) == 0:
                count += 1
                continue

            if distance != 0:
                current_available_cables["cable_impedence"] = np.sqrt(
                    current_available_cables["r_ohm_per_km"] ** 2 +
                    current_available_cables["x_ohm_per_km"] ** 2
                )

                voltage_available_cables = current_available_cables[
                    current_available_cables["cable_impedence"] <=
                    VN * VOLTAGE_DROP_DISTRIBUTION_PERCENT / 100 / (Imax * distance / count)
                ]

                if len(voltage_available_cables) == 0:
                    count += 1
                    continue
                else:
                    cable = voltage_available_cables.sort_values(by=["q_mm2"]).index.tolist()[0]
                    break
            else:
                cable = current_available_cables.sort_values(by=["q_mm2"]).index.tolist()[0]
                break

        return cable, count

    def create_line_ont_to_lv_bus(self, plz: int, bcid: int, kcid: int,
                                   branch_start_node: int, branch_deviation: float,
                                   cable: str, count: int, ont_vertice: int):
        """Create line from transformer to connection node."""
        end_vid = branch_start_node
        node_geodata = self.dbc.get_node_geom(end_vid)
        node_geodata = (float(node_geodata[0]) + 5 * 1e-6 * branch_deviation,
                        float(node_geodata[1]) + 5 * 1e-6 * branch_deviation)

        coords = self.backend.get_bus_coordinates("LVbus 1")
        if coords:
            lvbus_geodata = (coords[0] + 5 * 1e-6 * branch_deviation, coords[1])
        else:
            lv_geodata = self.dbc.get_ont_geom_from_bcid(plz, kcid, bcid)
            lvbus_geodata = (float(lv_geodata[0]) + 5 * 1e-6 * branch_deviation, float(lv_geodata[1]))
        line_geodata = [lvbus_geodata, node_geodata]
        # When branch starts at transformer, use 1 meter minimum to avoid zero-impedance
        length_km = 0.001

        line_spec = LineSpec(
            name=f"Line to {end_vid}",
            bus1="LVbus 1",
            bus2=f"Connection Nodebus {end_vid}",
            cable_name=cable,
            length_km=length_km,
            parallel=count,
            coordinates=line_geodata,
        )
        self.backend.create_component(line_spec)

        line_name = f"L{end_vid}"[:15]
        self.dbc.insert_lines(
            geom=line_geodata, plz=plz, bcid=bcid, kcid=kcid, line_name=line_name,
            std_type=cable,
            from_bus=ont_vertice,  # Use vertex ID directly (backend-agnostic)
            to_bus=end_vid,
            length_km=length_km
        )

    def create_line_start_to_lv_bus(self, plz: int, bcid: int, kcid: int,
                                     branch_start_node: int, branch_deviation: float,
                                     vertices_dict: dict, cable: str, count: int,
                                     ont_vertice: int) -> int:
        """Create line from branch start to LV bus."""
        node_path_list = self.dbc.get_path_to_bus(branch_start_node, ont_vertice)

        line_geodata = []
        for p in node_path_list:
            node_geodata = self.dbc.get_node_geom(p)
            node_geodata = (float(node_geodata[0]) + 5 * 1e-6 * branch_deviation,
                            float(node_geodata[1]) + 5 * 1e-6 * branch_deviation)
            line_geodata.append(node_geodata)

        coords = self.backend.get_bus_coordinates("LVbus 1")
        if coords:
            lvbus_geodata = (coords[0] + 5 * 1e-6 * branch_deviation, coords[1])
        else:
            # Fallback to database (for backends without geodata)
            lv_geodata = self.dbc.get_ont_geom_from_bcid(plz, kcid, bcid)
            lvbus_geodata = (float(lv_geodata[0]) + 5 * 1e-6 * branch_deviation, float(lv_geodata[1]))
        line_geodata.append(lvbus_geodata)
        line_geodata.reverse()

        length_km = vertices_dict[branch_start_node] * 1e-3
        length = count * length_km

        line_spec = LineSpec(
            name=f"Line to {branch_start_node}",
            bus1="LVbus 1",
            bus2=f"Connection Nodebus {branch_start_node}",
            cable_name=cable,
            length_km=length_km,
            parallel=count,
            coordinates=line_geodata,
        )
        self.backend.create_component(line_spec)

        line_name = f"L{branch_start_node}"[:15]
        self.dbc.insert_lines(
            geom=line_geodata, plz=plz, bcid=bcid, kcid=kcid, line_name=line_name,
            std_type=cable,
            from_bus=ont_vertice,  # Use vertex ID directly (backend-agnostic)
            to_bus=branch_start_node,
            length_km=length_km
        )

        return length

    def deviate_bus_geodata(self, branch_node_list: list, branch_deviation: float):
        """Update bus geodata for visualization (no-op for backends without geodata)."""
        offset = 5 * 1e-6 * branch_deviation
        for node in branch_node_list:
            bus_name = f"Connection Nodebus {node}"
            coords = self.backend.get_bus_coordinates(bus_name)
            if coords:
                self.backend.set_bus_coordinates(bus_name, coords[0] + offset, coords[1] + offset)

    def create_line_node_to_node(self, plz: int, kcid: int, bcid: int,
                                  branch_node_list: list, branch_deviation: float,
                                  vertices_dict: dict, local_length_dict: dict,
                                  cable: str, ont_vertice: int, count: float) -> dict:
        """Create lines between connection nodes."""
        for i in range(len(branch_node_list) - 1):
            node_path_list = self.dbc.get_path_to_bus(branch_node_list[i], ont_vertice)

            if branch_node_list[i + 1] not in node_path_list:
                node_path_list = self.dbc.get_path_to_bus(branch_node_list[i], branch_node_list[i + 1])

            node_path_list = node_path_list[: node_path_list.index(branch_node_list[i + 1]) + 1]
            node_path_list.reverse()

            start_vid = node_path_list[0]
            end_vid = node_path_list[-1]

            line_geodata = []
            for p in node_path_list:
                node_geodata = self.dbc.get_node_geom(p)
                node_geodata = (float(node_geodata[0]) + 5 * 1e-6 * branch_deviation,
                                float(node_geodata[1]) + 5 * 1e-6 * branch_deviation)
                line_geodata.append(node_geodata)

            length_km = (vertices_dict[end_vid] - vertices_dict[start_vid]) * 1e-3
            local_length_dict[cable] += count * length_km

            line_spec = LineSpec(
                name=f"Line to {end_vid}",
                bus1=f"Connection Nodebus {start_vid}",
                bus2=f"Connection Nodebus {end_vid}",
                cable_name=cable,
                length_km=length_km,
                parallel=count,
                coordinates=line_geodata,
            )
            self.backend.create_component(line_spec)

            line_name = f"L{end_vid}"[:15]
            self.dbc.insert_lines(
                geom=line_geodata, plz=plz, bcid=bcid, kcid=kcid, line_name=line_name,
                std_type=cable,
                from_bus=start_vid,  # Use vertex ID directly (backend-agnostic)
                to_bus=end_vid,
                length_km=length_km
            )

        return local_length_dict
