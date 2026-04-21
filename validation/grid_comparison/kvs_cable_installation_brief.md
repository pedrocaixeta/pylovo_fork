# KVS Integration Brief — Cable Installation Redesign

This document collects all relevant insights from the feeder metric analysis for
an agent tasked with redesigning the cable installation logic in PyLoVo to
incorporate **Kabelverteilerstationen (KVS)** — cable distribution stations that
are present in real German LV grids but absent from the current synthetic grid
generation.

---

## 1. What is a KVS?

A **Kabelverteilerstation (KVS)** — also called Kabelverteilerschrank or
Kabelverteilerkasten — is a street-level cabinet where a single incoming feeder
cable from the transformer station splits into multiple outgoing cables serving
downstream house connections or further backbone segments.

In the real SWF grid data, KVS buses are named `NS_KVS_<id>_(S)`.

### Physical role in German LV grid topology

```
Transformer Station
        │
    ┌───┴───┐
    │       │          ← main feeders (Abgänge)
   Kn      KVS
   │      / | \        ← KVS splits into multiple downstream cables
  HaAn  Kn  Kn  HaAn
        │    │
       HaAn HaAn
```

- A KVS sits at an intermediate point along a feeder, typically where the cable
  route branches into a residential side-street or housing cluster.
- It is **not** a transformer — it has no voltage transformation capability.
- It is a physical junction box with fuses/switches for each outgoing cable.
- Typical KVS degree in real grids: 2–6 (1 incoming + 1–5 outgoing cables).

## 2. KVS statistics from 138 real SWF grids

| Metric | Value |
|---|---|
| Grids containing ≥1 KVS | 116 / 138 (84%) |
| Mean KVS per grid | 4.8 |
| KVS degree range | 2–6 |
| KVS neighbour types | Mix of NS_HaAn (house connections) and NS_Kn (backbone cable nodes) |

KVS are ubiquitous in real German LV grids. Their absence in synthetic grids is a
structural gap that affects feeder topology and cable sizing.

## 3. Current synthetic grid generation (no KVS)

### Relevant files

- `src/pylovo/grid_generator.py` → `install_cables()` method (line ~828)
- `src/pylovo/cable_installer.py` → `CableInstaller` class

### Current algorithm summary

1. For each building cluster (kcid/bcid), connection nodes and consumer locations
   are retrieved from the database.
2. Cables are installed **branch by branch** using a greedy furthest-node-first
   strategy:
   - Find the furthest unconnected node from the transformer.
   - Trace the path back to the transformer, collecting all nodes along the way
     into a "branch".
   - Size a cable for the entire branch based on simultaneous peak load.
   - Install consumer connection cables from each `Connection Nodebus` to its
     `Consumer Nodebus` (house connection).
   - Connect the branch start to the `LVbus` (transformer LV side) via
     `create_line_start_to_lv_bus()`.
   - Connect intermediate backbone nodes via `create_line_node_to_node()`.
3. Repeat until all connection nodes are served.

### Bus naming convention in synthetic grids

| Bus name pattern | Role | Real grid equivalent |
|---|---|---|
| `LVbus` | Transformer LV bus (root) | `NS_Kn(n)_TrSt_...` |
| `Connection Nodebus <id>` | Backbone cable junction | `NS_Kn(n)_...` |
| `Consumer Nodebus <id>` | House connection (leaf with load) | `NS_HaAn_...` |
| *(none)* | Cable distribution station | `NS_KVS_...` |

### What's missing

- No `NS_KVS` bus type exists in synthetic grids.
- All backbone nodes are `Connection Nodebus` — there's no intermediate
  aggregation/splitting point between the transformer and the house connections.
- Every branch connects directly to the LVbus. In real grids, branches often
  connect to a KVS which itself connects to the transformer via a single
  higher-capacity cable.

## 4. How KVS affect grid structure and metrics

### 4a. Feeder counting

The feeder count measures how many main cable runs leave the transformer station.
Without KVS, each branch = 1 feeder directly from the transformer. With KVS:

- A KVS at the branch point effectively **multiplies** the feeder count by
  splitting one incoming cable into N outgoing cables.
- The corrected feeder counting algorithm (see `feeder_calculation_adjustments.md`)
  now handles this: KVS neighbours at the branch point are expanded into their
  non-house-connection children count.

**Scenario A** (your reference): Trafo → 2 KVS → one splits to 2 backbone feeders,
other splits to 3 → **5 feeders total**.

**Scenario B** (your reference): Trafo → 2 KVS → one splits to 2 backbone feeders,
other has 10 direct house connections only → **3 feeders total** (the KVS serving only
houses counts as 1 feeder, not 10).

### 4b. Cable sizing

In real grids, the cable **upstream** of a KVS (transformer → KVS) carries the
aggregated load of all downstream consumers, requiring a thicker cable. The cables
**downstream** of the KVS each carry only their own sub-branch load.

Current synthetic grids size a single cable type per branch from transformer to
furthest consumer. With KVS, the cable sizing should split into:

- **Trunk cable** (transformer → KVS): sized for the full simultaneous load of
  all downstream consumers served through this KVS.
- **Distribution cables** (KVS → downstream): sized for the load of each
  individual sub-branch.

### 4c. Voltage drop

KVS placement affects voltage drop calculations. Placing a KVS closer to the
transformer shortens the trunk cable (lower impedance for the aggregated load)
and allows longer distribution cables at lower current.

### 4d. House connection count per feeder

With KVS, the number of house connections per feeder shifts:
- Without KVS: each feeder serves its own cluster of houses.
- With KVS: a single trunk feeder → KVS → multiple sub-feeders, each serving
  a smaller cluster. The total house connections per trunk feeder increases, but
  per sub-feeder decreases.

## 5. Placement heuristics for KVS in synthetic grids

Based on real grid observations:

1. **When to place a KVS**: When a backbone path reaches a point where it needs
   to branch into ≥3 directions (serving different street segments or housing
   groups). In real grids this typically happens at:
   - Street intersections
   - Points where a main road meets a cul-de-sac or side street
   - Entry points to larger housing developments

2. **Distance from transformer**: KVS are typically 50–300m from the transformer
   station along the cable route (observed from grid topology depth analysis).

3. **Downstream structure**: Each KVS outgoing cable serves 2–15 house connections
   (observed from subtree analysis of real grids).

4. **Degree distribution**: Most KVS have 3–5 outgoing cables (plus the 1 incoming =
   degree 4–6).

## 6. Suggested implementation approach

### Phase 1: Add KVS bus type to the grid model

- Introduce a new bus naming pattern: `NS_KVS <id>` or `KVS Nodebus <id>`.
- Create KVS buses in `CableInstaller` at identified branching points.
- Connect KVS to the transformer via a trunk cable and to downstream branches
  via distribution cables.

### Phase 2: KVS placement logic in `install_cables()`

After identifying branches (the current furthest-node-first algorithm), add a
post-processing step:

1. Group branches that share a common initial path segment from the transformer.
2. If a group of ≥3 branches diverge from a common backbone node, place a KVS
   at that divergence point.
3. Replace the individual branch-to-LVbus connections with:
   - One trunk cable: LVbus → KVS
   - N distribution cables: KVS → each branch start

### Phase 3: Cable sizing adjustment

- **Trunk cable** (LVbus → KVS): sized for the sum of simultaneous loads across
  all downstream branches (using the existing `simultaneousPeakLoad` function).
- **Distribution cables** (KVS → branch): sized as currently (per-branch load).

### Key files to modify

| File | Changes |
|---|---|
| `src/pylovo/cable_installer.py` | Add `create_kvs_bus()`, modify `create_line_start_to_lv_bus()` to route through KVS when applicable |
| `src/pylovo/grid_generator.py` | Add KVS placement logic in `install_cables()` after branch identification |
| `src/pylovo/config_loader.py` | Add KVS-related config parameters (min branches to trigger KVS, max KVS distance, etc.) |
| `src/pylovo/analysis/parameter_calculation.py` | Already handles KVS via `PYLOVO_BUS_TYPE_CONFIG` — update `kvs_pattern` if naming changes |

## 7. Real grid data reference

- SWF source file: `/home/breveron/data/SWF.json`
- Split LV subnets: `/home/breveron/data/regular_nets/regular/LV_*.json`
- 138 regular grids, 47 mini grids
- Bus type classification: see `classify_bus_types()` in `parameter_calculation.py`
  with `SWF_BUS_TYPE_CONFIG` for the naming patterns
- Topology splitting: see `validation_helpers.py` for `_build_lv_topology()` and
  `_assign_buses_to_trafos()` (switch-aware graph analysis)
