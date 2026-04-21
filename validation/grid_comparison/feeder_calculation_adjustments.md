# Feeder Calculation Adjustments

## Summary

The feeder counting logic in `parameter_calculation.py` was unified into a single
topology-aware algorithm that replaces the previous two separate methods
(`count_feeders_for_generic_grid` and `count_feeders_for_synthetic_grid`).
The new method works correctly for both real DSO grid exports and synthetic
PyLoVo grids by using a configurable bus type classification dictionary.

## Problems in the old implementation

### 1. House connections counted as feeders

`count_feeders_for_generic_grid` counted `degree − 1` at the first branch point
without inspecting bus types. Any `NS_HaAn` (Hausanschluss) leaf node directly
connected to the branch point was counted as a separate feeder. 48 of 138 real
grids were affected (mean 0.8 false feeders per grid; worst case: LV_049 had all
6 "feeders" being single house connections).

### 2. KVS not handled as splitters in real grids

The synthetic method expanded KVS (Kabelverteilerstationen) nodes — adding their
`degree − 1` instead of 1. The generic/real method did not, creating an asymmetry
between synthetic and real feeder counts.

### 3. MultiGraph parallel edge inflation

pandapower's `create_nxgraph` returns a `nx.MultiGraph`. Parallel cables between
the same pair of buses inflate `degree` beyond the unique neighbor count. The old
algorithm used `degree − 1` directly, so grids with parallel cables had massively
overcounted feeders (e.g. LV_186: 16 buses, degree 30 at branch point, but only
6 unique neighbors → old count 29, corrected count 9).

## New unified algorithm

Located in `ParameterCalculator._count_feeders_unified()`:

1. **Walk past source stubs**: from the trafo LV bus, skip degree-1 and degree-2
   nodes to reach the first real branching node.
2. **Enumerate downstream neighbors**: unique neighbors only (handles MultiGraph),
   excluding the incoming edge and any transformer edges.
3. **Classify each neighbor** using a configurable `bus_type_config` dictionary:
   - **House connection leaf** (no downstream children): **skipped** — not a feeder.
   - **KVS**: **expanded** — each non-house-connection child counts as a separate
     feeder. If all children are house connections, the KVS itself counts as 1 feeder.
   - **Backbone / other**: counted as **1 feeder**.
4. **Degenerate star safety net**: if all downstream neighbors are house connection
   leaves, the grid gets at least 1 feeder.

## Configurable bus type classification

Two predefined configs exist as module-level dictionaries:

| Config | `house_connection_pattern` | `kvs_pattern` | Use case |
|---|---|---|---|
| `SWF_BUS_TYPE_CONFIG` | `NS_HaAn` | `NS_KVS` | Real SWF/DSO grid exports |
| `PYLOVO_BUS_TYPE_CONFIG` | `Consumer Nodebus` | `NS_KVS` | Synthetic PyLoVo grids |

Custom configs can be passed via `bus_type_config` parameter to
`compute_comparison_parameters()` and `count_feeders()` for other DSO data formats.

Each config requires three keys:
- `name_column`: bus table column containing bus names (default: `"name"`)
- `house_connection_pattern`: regex matching house connection bus names
- `kvs_pattern`: regex matching cable distribution station bus names

## Impact on real grid metrics (138 regular grids)

| Statistic | Old | New |
|---|---|---|
| Mean feeders | 11.0 | 6.5 |
| Median | 8 | 5 |
| Max | 30 | 26 |
| Grids changed | — | 125/138 |

## Files changed

- `src/pylovo/analysis/parameter_calculation.py` — added `classify_bus_types()`,
  `SWF_BUS_TYPE_CONFIG`, `PYLOVO_BUS_TYPE_CONFIG`, `_count_feeders_unified()`,
  `_is_trafo_edge()`; removed `count_feeders_for_generic_grid()` and
  `count_feeders_for_synthetic_grid()`; updated `count_feeders()` signature.
- `src/pylovo/analysis/grid_analysis.py` — `compute_comparison_parameters()` accepts
  `bus_type_config`; `compute_clustering_metrics()` calls `count_feeders()`.
