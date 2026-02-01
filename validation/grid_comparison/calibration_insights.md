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
