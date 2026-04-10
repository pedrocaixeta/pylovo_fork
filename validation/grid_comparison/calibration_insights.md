# GRID CALIBRATION & ANALYSIS INSIGHTS
*Auto-generated validation report for PLZ 91301 vs Forchheim (SWF) Real Grids*

## 1. Transformer Sizing
**Finding**: Real grids exhibit a wider variety of transformer ratings than the standard 0.63 MVA often used in synthesis defaults.

| Rating (MVA) | Count (N=86) | Share |
| :--- | :--- | :--- |
| **0.630** | **48** | **56%** |
| 0.400 | 28 | 33% |
| 0.515 | 4 | 5% |
| 0.200/0.250 | 3 | 3% |
| 0.715/0.800 | 2 | 2% |

**Recommendation**: Adjust `config_generation.yaml` to sample from a distribution (e.g., 60% 0.63 MVA, 35% 0.40 MVA) rather than a fixed value.

## 2. Cable Types
**Finding**: The following cable types cover >90% of the installed length in the real grid. Use these for synthesis calibration.

| Rank | Cable Type | Possible Role |
| :--- | :--- | :--- |
| 1 | `NYY-J 4x35` | House Connection / Street Lighting |
| 2 | `NYY-J 3x150SM 0.6/1kV` | Main Feeder |
| 3 | `NAYY 4x185SE 0.6/1kV` | Main Feeder (Aluminum) |
| 4 | `NYY-J 3x70SM 0.6/1kV` | Secondary Feeder |
| 5 | `NAYY-J 4x50` | House Connection / Feeder end |

*Note*: MV Cable (Rank 3 by length) `NA2XS(F)2Y 1x240RM 12/20kV ir` is also prominent, verifying the input MV grid model.

## 3. Topology Artifacts (KVS)
**Observation**: Initial validation showed real grids having very few "branches" (often 1) with extremely high household counts (up to 1500+).
**Root Cause**: Presence of **Cable Distribution Cabinets (NS_KVS)**.
- **Frequency**: Found in 74 of 86 grids.
- **Topology**: The transformer often feeds a single KVS via a short cable. This KVS then splits at least into the street feeders.
- **Impact**: Standard graph analysis counts the Trafo->KVS link as the single "branch".
- **Resolution**: Metrics updated to treat `NS_KVS` nodes as branch splitters.

## 4. Load Assumptions
- **Simultaneity**: Real grid ADMD validation suggests ~1 kW/household effective peak is a reasonable approximation for residential-dominated grids in this area.
- **Peak Load**: `PEAK_LOAD_HOUSEHOLD = 14.5 kW` (standard installed capacity) is used as the base for simultaneity calculations.

## 5. Resistance Metric: Real vs. Synthetic Unit Mismatch (Resolved)

**Investigation**: The `resistance` comparison metric showed real-grid values roughly 300–1000× lower than synthetic values, which was initially suspected to be a unit difference (`ohm/km` vs `mOhm/km`).

**Root Cause — NOT units**: Both synthetic grids (loaded from the database via `read_net_db`) and real grids (loaded from JSON via `pp.from_json`) store `r_ohm_per_km` in true **ohm/km**. No unit scaling is needed or correct.

The actual cause was in how **household equivalents (HE)** were derived for real grids inside `_calculate_resistance` in `src/pylovo/analysis/grid_analysis.py`:

| Grid type | `max_p_mw` per load | HE per consumer bus | Effect |
| :--- | :--- | :--- | :--- |
| Synthetic | `PEAK_LOAD_HOUSEHOLD / 1000` (0.0145 MW) | 1.0 (1 load per bus) | Correct baseline |
| Real (old fallback) | `p_mw` (~0.003–0.005 MW) | ~0.3 (from low instantaneous load) | HE ~ 3× too small |

A second compounding issue: real grids have **multiple load entries per consumer bus** (individual meters, sub-circuits, appliances). For example, LV_028 has 157 load rows on only 26 unique buses (average 6 per bus). Assigning `PEAK_LOAD_HOUSEHOLD` per load row rather than per bus would give `HE ≈ 6` per bus — inflating resistance ~6×.

**Fix** (`src/pylovo/analysis/grid_analysis.py`, `_calculate_resistance`): When `max_p_mw` is absent, build a temporary single-row-per-unique-consumer-bus load table with `max_p_mw = PEAK_LOAD_HOUSEHOLD / 1000.0`, yielding `HE = 1.0` per consumer bus — identical to the synthetic grid assumption.

```python
unique_buses = load["bus"].unique()
net.load = pd.DataFrame({
    "bus": unique_buses,
    "max_p_mw": PEAK_LOAD_HOUSEHOLD / 1000.0,
})
```

**Validation**: After the fix, `LV_028` (26 consumers, 4.1 km cable) gives `resistance ≈ 0.55 Ω·HE`, consistent with its topology.

## 6. HH-Only Path Resistance Proxy (In Progress)

**Current implementation direction**: The comparison workflow now uses a dedicated HH-only path resistance proxy, while the historical VSW metric remains available in the clustering workflow.

- **HH-only path resistance proxy**: a residential comparison metric based only on load rows tagged with `type == HH` in real grids. Loads such as `Ladestation` and `WP` are excluded.

For the HH-only proxy, each consumer bus contributes with a weight equal to the number of HH load rows attached to that bus:

$$
R_{proxy} = \frac{\sum_i n_i \cdot R_{path,i}}{\sum_i n_i}
$$

with:

- $n_i$: number of HH loads on consumer bus $i$
- $R_{path,i}$: total transformer-to-bus path resistance

**Reason**: This avoids the old dependency on synthesizing `max_p_mw` for real grids and makes the real-vs-synthetic comparison explicitly residential-only.

**Note**: The historical VSW metric is kept unchanged for clustering-oriented analyses. The HH-only proxy is used for the residential comparison workflow.
