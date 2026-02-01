# Grid Structure Documentation

This document describes the structure, nomenclature, and data model of the SWF pandapower grid located in `SWF.json`. It has been verified against the actual data using `inspect_grid.py`.

## Overview

The model is a meshed Medium Voltage (MV) and Low Voltage (LV) distribution grid.

- **Total Buses**: 33,657
- **Physical "Islands"**: Each MV/LV Transformer typically feeds one distinct LV grid.
- **Transformers**: 188 (Total expansion scenarios included)

## Nomenclature (`chr_name`)

Most components (`bus`, `line`, `trafo`, `load`, `sgen`) possess a `chr_name` attribute encoded with topological information.

**Format**: `[NetID+Prefix]_[MainNode1]_[MainNode2]_[BranchID]_[ElementID]`
Example: `5001001_001001_001001_062064_01187`

### Segment Breakdown

| Segment | Meaning | Length | Analysis/Code |
| :--- | :--- | :--- | :--- |
| **1. Net Identifier** | Grid ID | 7-12 chars | **Prefix:** `5`=MV, `7`=LV, `6`=Trafo.<br>**ID:** Digits 2-4 (e.g. `169` in `7169169`) represent the specific Subnet ID. |
| **2. MainNode1** | Start Node | 6 digits | Topological anchor. |
| **3. MainNode2** | End Node | 6 digits | Topological anchor. |
| **4. Branch ID** | Strand ID | 6-8 digits | **Prefix Codes**: <br>`00`: Main Feeder/Backbone<br>`06`: Line Branch? (Occurs frequently)<br>`02`: Sub-branch? |
| **5. Element ID** | Element Idx | 5 digits | **Prefix Codes**: <br>`01`: Bus/Node<br>`06`: Line Segment<br>`03`: Load/Gen? |

*Note: The prefixes in Segments 4/5 are consistent indicators of element type or hierarchy position.*

### Example Decoding
`7169169_001001_001001_003001_01001`
- **7169169**: LV Grid #169.
- **003001**: Branch Code `00` (Main backbone/feeder).
- **01001**: Element Code `01` (Bus).

### Special Cases & Topology
- **Ring Networks**: Indicated by Main Node sequence or specific Branch IDs (e.g., `_003001_`). Verified in Net `7169` (Plot: `plots/ring_7169169.png`).
- **Double Feeding**: **None**. Each LV grid is radially fed by a single MV/LV transformer.
- **Geometry**: Available in `bus['geo']` as JSON strings (e.g., `{"coordinates": [x, y], "type": "Point"}`).

## Statistics by Voltage Level

### Medium Voltage (MV)
- **Identifier**: `5xxxxxx`
- **Unique Grid IDs**: 1 (Main Backbone `5001`)
- **Buses**: 13,723
- **Lines**: 13,793
- **Loads**: 0 (Direct loads on MV are rare or modeled as LV aggregated)

### Low Voltage (LV)
- **Identifier**: `7xxxxxx`
- **Unique Grid IDs**: 186 (closely matches 188 Transformer count)
- **Average Size**: ~102 Buses per Grid
- **Min/Max**: 1 Bus (stub) to 1,173 Buses.
- **Loads**: ~39,800
- **Sgens**: ~15,000

## Data Quality & Anomalies (New Insights)

### 1. Outdated Geodata Format
The original `SWF.json` contained geometry in a non-standard `geo` column containing JSON strings. 
- **Buses**: Had valid Point coordinates.
- **Lines**: **Had NO geometry**. 
- **Fix**: In `SWF_3.json`, line geometries were synthesized from the coordinates of their endpoint buses, and both tables (`bus_geodata`, `line_geodata`) were correctly populated.

### 2. Mini Grids (Likely Data Errors)
Analysis revealed **101** of the 186 LV grids have fewer than 5 buses (most are single-bus nodes).
- **Nature**: These appear to be isolated measurement points, disconnected stubs, or data artifacts.
- **Action**: When splitting the data, these have been segregated into a `mini_grids/` directory, while functional grids are in `regular/`.

### 3. Crossover Lines (Tie-Lines)
There are approximately **75 lines** that connect two different Subnet IDs (e.g., Grid `069` to Grid `156`).
- **Characteristics**: 
    - They are standard lines but typically act as **Open Switches** (Status verified as Open/False).
    - **Nomenclature**: They usually carry the name of *one* of the subnets (e.g., `7069...` connecting to `7156...`).
- **Implication**: If filtering strictly by `chr_name` to split subnets, these lines are often excluded because their endpoint buses belong to different logical groups.
- **Resolution**: These lines are neglected in the radial subnet split to ensure electrical isolation, consistent with their "Open Switch" status.

## Data Model Attributes
- **Construction Year (`Baujahr`)**: `0` (Existing), `2030+` (Future).
- **Expansion**: Future loads/gens are included in the dataset but marked with `Baujahr > 0`.

## File Information
- **Source**: `validation/data/SWF.json`
- **Scripts**: 
    - `swf_subnets.py`: Utility to split subnets (Patched to filter NaNs).
    - `inspect_grid.py`: Analysis tool used to generate these stats and plots.
