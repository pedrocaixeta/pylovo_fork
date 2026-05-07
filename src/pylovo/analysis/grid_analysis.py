"""Compose named LV grid parameter sets from the ParameterCalculator toolbox."""

from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd
import pandapower as pp

from pylovo.config_loader import PEAK_LOAD_HOUSEHOLD

if TYPE_CHECKING:
    from pylovo.analysis.parameter_calculation import ParameterCalculator


REAL_HOUSEHOLD_LOAD_TYPES = {"HH"}


def _get_transformer_mva(net: pp.pandapowerNet) -> float:
    """Return the transformer rating in MVA from ``net.trafo["sn_mva"]``.

    Both synthetic grids and real LV subnets carry the transformer as an
    out-of-service element (added by
    :func:`~pylovo.analysis.validation_helpers.extract_lv_grids`), so
    ``sn_mva`` is always readable directly from the network object.
    """
    if not net.trafo.empty and "sn_mva" in net.trafo.columns:
        val = net.trafo["sn_mva"].iloc[0]
        if pd.notna(val):
            return float(val)
    return float("nan")


def _calculate_resistance(
    calculator: "ParameterCalculator",
    net: pp.pandapowerNet,
) -> float:
    """Return the active comparison resistance proxy.

    Comparison now uses aggregate routed-line resistance so the metric remains
    meaningful for both real and synthetic grids even when house-connection
    modelling differs or cable-distribution stations are absent.
    """
    return calculator.calculate_graph_resistance(net, only_in_service=True)


def compute_comparison_parameters(
    calculator: "ParameterCalculator",
    net: pp.pandapowerNet,
    consumer_buses: list[int] | None = None,
    bus_type_config: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compute the active real-vs-synthetic comparison parameter set for one LV grid.

    Parameters
    ----------
    bus_type_config : dict, optional
        Naming-pattern dictionary forwarded to the unified feeder counter.
        When ``None`` the config is auto-detected from the bus naming
        convention (see :data:`~pylovo.analysis.parameter_calculation.SWF_BUS_TYPE_CONFIG`).
    """
    uses_synthetic_naming = calculator.uses_synthetic_bus_naming(net)

    try:
        root_idx = calculator.resolve_root_bus(net, uses_synthetic_naming)
        resolved_consumer_buses = (
            consumer_buses
            if consumer_buses is not None
            else calculator.resolve_consumer_buses(net, uses_synthetic_naming)
        )

        graph = pp.topology.create_nxgraph(net, respect_switches=True)
        feeder_lines = calculator.count_feeders(
            net, graph, root_idx, uses_synthetic_naming,
            bus_type_config=bus_type_config,
            recursive_expansion=True,
        )
        avg_trafo_distance, max_trafo_distance = calculator.calculate_trafo_distances(
            graph,
            root_idx,
            resolved_consumer_buses,
        )
    except Exception as exc:
        calculator.dbc.logger.error(f"Error calculating comparison parameters: {exc}")
        import traceback

        traceback.print_exc()
        feeder_lines = 0
        avg_trafo_distance = 0.0
        max_trafo_distance = 0.0
        graph = pp.topology.create_nxgraph(net, respect_switches=True)

    transformer_mva = _get_transformer_mva(net)
    graph_length = calculator.calculate_graph_length(net, only_in_service=True)
    graph_resistance = _calculate_resistance(calculator, net)

    return {
        "feeder_lines": int(feeder_lines),
        "graph_length": float(graph_length),
        "avg_trafo_distance": float(avg_trafo_distance),
        "max_trafo_distance": float(max_trafo_distance),
        "transformer_mva": transformer_mva,
        "graph_resistance": float(graph_resistance),
    }


def compute_clustering_metrics(calculator: "ParameterCalculator", net: pp.pandapowerNet) -> Dict[str, Any]:
    """Compute the full clustering-oriented parameter set for one synthetic LV grid."""
    no_house_connections = calculator.count_buses_by_keyword(net, calculator.consumer_bus_keyword)
    no_connection_buses = calculator.count_buses_by_keyword(net, calculator.connection_bus_keyword)
    no_households = calculator.count_households(net)
    max_power_mw = calculator.calculate_total_installed_power(net)

    no_household_equ = max_power_mw * 1000.0 / PEAK_LOAD_HOUSEHOLD
    cable_length_km = calculator.calculate_cable_length(net)
    cable_len_per_house = cable_length_km / no_house_connections if no_house_connections > 0 else 0.0

    graph = pp.topology.create_nxgraph(net, respect_switches=True)
    root_idx = calculator.resolve_synthetic_root_bus(net)
    no_branches = calculator.count_feeders(net, graph, root_idx, uses_synthetic_naming=True)
    avg_trafo_dis, max_trafo_dis = calculator.calculate_trafo_distances_for_synthetic_grid(net, graph)

    if no_branches > 0:
        no_house_connections_per_branch = no_house_connections / no_branches
        no_households_per_branch = max_power_mw * 1000.0 / (PEAK_LOAD_HOUSEHOLD * no_branches)
    else:
        no_house_connections_per_branch = 0.0
        no_households_per_branch = 0.0

    transformer_mva = calculator.get_transformer_power(net)
    house_distance_km = calculator.calculate_average_house_distance(net)
    simultaneous_peak_load_mw = calculator.lookup_simultaneous_peak_load(transformer_mva, max_trafo_dis)

    (
        max_no_of_households_of_a_branch,
        resistance,
        reactance,
        ratio,
        max_vsw_of_a_branch,
    ) = calculator.calculate_impedance_metrics(net, graph)

    vsw_per_branch = resistance / no_branches if no_branches > 0 else 0.0

    return {
        "no_connection_buses": int(no_connection_buses),
        "no_branches": int(no_branches),
        "no_house_connections": int(no_house_connections),
        "no_house_connections_per_branch": float(no_house_connections_per_branch),
        "no_households": int(no_households),
        "no_household_equ": float(no_household_equ),
        "no_households_per_branch": float(no_households_per_branch),
        "max_no_of_households_of_a_branch": float(max_no_of_households_of_a_branch),
        "house_distance_km": float(house_distance_km),
        "transformer_mva": float(transformer_mva),
        "max_trafo_dis": float(max_trafo_dis),
        "avg_trafo_dis": float(avg_trafo_dis),
        "cable_length_km": float(cable_length_km),
        "cable_len_per_house": float(cable_len_per_house),
        "max_power_mw": float(max_power_mw),
        "simultaneous_peak_load_mw": float(simultaneous_peak_load_mw),
        "resistance": float(resistance),
        "reactance": float(reactance),
        "ratio": float(ratio),
        "vsw_per_branch": float(vsw_per_branch),
        "max_vsw_of_a_branch": float(max_vsw_of_a_branch),
    }