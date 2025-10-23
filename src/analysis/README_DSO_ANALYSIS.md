# Analyzing External/DSO Networks with Pylovo

This guide explains how to use the topology analysis functions on external pandapower networks (e.g., from DSO) without requiring database access.

## Problem Statement

The `topology_analysis` module was originally designed for synthetic grids stored in the database with specific conventions:
- Bus names follow patterns: "LVbus", "Consumer Nodebus", "Connection Nodebus"
- Buses and loads have zone information: "Residential", "Commercial", "Public"
- Grids are identified by PLZ, BCID, KCID metadata

DSO networks have different structures and naming conventions, making direct analysis impossible.

## Solution Overview

The solution uses an **adapter pattern** with three new modules:

1. **`data_adapter.py`** - Normalizes external networks to match expected structure
2. **`standalone_calculator.py`** - Database-independent parameter calculation
3. **`benchmark_analysis.py`** (updated) - Main entry point for DSO analysis

## Architecture

```
┌─────────────────────┐
│  DSO JSON Network   │
│  (SWF_V7.json)      │
└──────────┬──────────┘
           │
           ↓
┌─────────────────────┐
│  Data Adapter       │  ← Normalizes structure
│  - Renames buses    │
│  - Adds zones       │
│  - Validates        │
└──────────┬──────────┘
           │
           ↓
┌─────────────────────┐
│ Standalone Calc     │  ← Reuses existing logic
│ - compute_params()  │
│ - No DB required    │
└──────────┬──────────┘
           │
           ↓
┌─────────────────────┐
│ Analysis Results    │
│ (JSON/CSV)          │
└─────────────────────┘
```

## Quick Start

### Configuration

1. Edit `src/analysis/config_validation.yaml`:

```yaml
# Absolute path to folder containing pandapower JSON files
data_dir: "/path/to/your/data/"

# Network filename (without .json extension)
net_name: "SWF_V7"

# EPSG code for coordinate system
projection: "epsg:3035"
```

### Basic Usage

```python
from src.analysis.benchmark_analysis import calc_grid_parameters_benchmark

# Analyze DSO network with automatic adaptation
params = calc_grid_parameters_benchmark()

# Access results
print(f"Cable length: {params['cable_length_km']:.2f} km")
print(f"Max power: {params['max_power_mw']:.3f} MW")
```

### Run from Command Line

```bash
cd /home/breveron/git/github/pylovo
python src/analysis/benchmark_analysis.py
```

## Advanced Usage

### Manual Network Adaptation

If you need more control over the adaptation process:

```python
import pandapower as pp
from src.analysis.data_adapter import adapt_dso_network
from src.analysis.standalone_calculator import StandaloneParameterCalculator

# Load your network
net = pp.from_json('/data/SWF_V7.json')

# Adapt with custom zone mapping
adapted_net = adapt_dso_network(
    net,
    zone_mapping={
        'Wohngebäude': 'Residential',
        'Gewerbe': 'Commercial',
        'Industrie': 'Commercial',
        'Öffentlich': 'Public'
    },
    default_zone='Residential'
)

# Calculate parameters
calculator = StandaloneParameterCalculator()
params = calculator.compute_parameters_with_fallback(adapted_net)

# Export results
calculator.analyze_and_export(
    adapted_net,
    output_path='/data/results.json',
    output_format='json'
)
```

### Batch Analysis

Analyze multiple networks:

```python
from pathlib import Path
from src.analysis.standalone_calculator import analyze_dso_network

data_dir = Path('/data/dso_networks/')
results = {}

for json_file in data_dir.glob('*.json'):
    print(f"Analyzing {json_file.name}...")
    params = analyze_dso_network(
        str(json_file),
        output_path=str(json_file.with_suffix('.analysis.json')),
        adapt_network=True
    )
    results[json_file.stem] = params

# Compare results
import pandas as pd
df = pd.DataFrame(results).T
print(df[['cable_length_km', 'max_power_mw', 'no_households']])
```

## Data Adapter Details

### What the Adapter Does

The `PandapowerNetworkAdapter` ensures networks have the required structure:

1. **Bus Names**: Ensures buses are identifiable by type
   - LV transformer bus → "LVbus_X"
   - Buses with loads → "Consumer Nodebus_X"
   - Internal buses → "Connection Nodebus_X"

2. **Zones**: Adds/normalizes zone information
   - Maps DSO zones to standard categories
   - Propagates zones between loads and buses
   - Sets default zone for missing information

3. **Validation**: Checks for required elements
   - At least one transformer
   - LV bus exists
   - Warns about missing loads/consumers

### Custom Adapter Configuration

```python
from src.analysis.data_adapter import PandapowerNetworkAdapter

adapter = PandapowerNetworkAdapter(
    net,
    config={
        'lv_bus_pattern': ['transformer', 'trafo', 'station'],
        'consumer_bus_pattern': ['load', 'house', 'customer'],
        'zone_mapping': {
            'residential': 'Residential',
            'commercial': 'Commercial',
            'industrial': 'Commercial'
        },
        'default_zone': 'Residential'
    }
)

adapted_net = adapter.adapt()
```

## Computed Parameters

The analysis computes the same metrics as synthetic grids:

### Topology Metrics
- `no_branches` - Main feeders from LV bus
- `no_house_connections` - Consumer connection points
- `no_connection_buses` - Internal junction buses
- `no_house_connections_per_branch` - Average connections per feeder

### Load Metrics
- `no_households` - Number of load elements
- `no_household_equ` - Equivalent households (normalized by peak load)
- `max_power_mw` - Total installed power
- `simultaneous_peak_load_mw` - Estimated coincident peak load

### Spatial Metrics
- `house_distance_km` - Median distance between houses
- `avg_trafo_dis` - Average path distance to transformer
- `max_trafo_dis` - Maximum path distance to transformer
- `cable_length_km` - Total cable length
- `cable_len_per_house` - Average cable per connection

### Electrical Metrics
- `transformer_mva` - Transformer rating
- `resistance` - Impedance-weighted resistance proxy
- `reactance` - Impedance-weighted reactance proxy
- `ratio` - R/X ratio
- `vsw_per_branch` - Voltage drop proxy per branch
- `max_vsw_of_a_branch` - Worst-case branch voltage drop proxy

## Key Differences from Database-Based Analysis

| Feature | Database Analysis | Standalone Analysis |
|---------|-------------------|---------------------|
| Data Source | PostgreSQL database | JSON files |
| Network Structure | Expected conventions | Adapted automatically |
| PLZ/BCID/KCID | Required | Not required (dummy values) |
| Simultaneous Load | DB lookup by trafo size & distance | Estimated from zones |
| Batch Processing | Per-PLZ database queries | File-based iteration |
| Result Storage | Database tables | JSON/CSV/Excel files |

## Limitations

1. **Simultaneous Peak Load**: Without database statistics, this is estimated using simple simultaneity factors rather than distance-based lookup. The estimation is conservative but may differ from database-based results by 5-15%.

2. **Zone Information**: If the DSO network lacks zone/category information, all loads are assumed to be "Residential" by default. You should provide zone mapping if known.

3. **Network Topology**: The analysis assumes radial topology. Networks with multiple feeders or meshed structures may produce unexpected results.

## Troubleshooting

### "No LV bus found"
- The adapter couldn't identify the transformer bus
- Check that your network has a transformer in `net.trafo`
- Verify the transformer's `lv_bus` exists in `net.bus`

### "Network has no loads"
- The network has no load elements
- Some metrics will be 0 or undefined
- Verify `net.load` is populated

### Zone warnings
- DSO data often lacks zone information
- Provide a `zone_mapping` dict to map DSO categories
- Or accept the default "Residential" classification

### Import errors
- Ensure you're running from the project root
- Check that all dependencies are installed: `pip install -r requirements.txt`

## Example Output

```
================================================================================
BENCHMARK ANALYSIS - External Network Parameter Calculation
================================================================================

1. Loading network...
   Data directory: /data/
   Network name: SWF_V7
   Projection: epsg:3035
   ✓ Network loaded successfully
   - Buses: 245
   - Lines: 244
   - Loads: 156
   - Transformers: 1

2. Adapting network structure...
   Normalizing bus names and zones for topology analysis...
   ✓ Network adapted successfully

3. Computing topology parameters...
   ✓ Parameters computed successfully

================================================================================
RESULTS
================================================================================

Network Topology:
  • Branches: 4
  • House connections: 156
  • Connection buses: 88
  • House connections per branch: 39.00

Load Characteristics:
  • Number of households: 156
  • Household equivalents: 312.45
  • Households per branch: 78.11
  • Max households on a branch: 89.23
  • Max power (MW): 1.247
  • Simultaneous peak load (MW): 0.523

Spatial Metrics:
  • Average house distance (km): 0.042
  • Average trafo distance (km): 0.284
  • Max trafo distance (km): 0.567
  • Cable length (km): 3.456
  • Cable length per house (km): 0.022

Transformer:
  • Transformer rating (MVA): 0.630

Electrical Characteristics:
  • Resistance (Ω·HE): 234.56
  • Reactance (Ω·HE): 178.34
  • R/X ratio: 1.32
  • VSW per branch: 58.64
  • Max VSW of a branch: 89.23

✓ Results exported to: /data/SWF_V7_analysis_results.json
================================================================================
```

## Integration with Existing Workflows

### Comparing with Synthetic Grids

```python
# Analyze DSO network
from src.analysis.standalone_calculator import analyze_dso_network
dso_params = analyze_dso_network('/data/SWF_V7.json')

# Load synthetic grid parameters from database
from src.database.database_client import DatabaseClient
dbc = DatabaseClient()
synthetic_params = dbc.read_clustering_parameters(plz=86150, bcid=1, kcid=1)

# Compare
import pandas as pd
comparison = pd.DataFrame({
    'DSO': dso_params,
    'Synthetic': synthetic_params
})
print(comparison[['cable_length_km', 'max_trafo_dis', 'no_households']])
```

### Validation Workflow

```python
# Analyze multiple DSO networks for validation
dso_networks = [
    '/data/SWF_V7.json',
    '/data/SWF_V8.json',
    '/data/SWF_V9.json'
]

results = []
for net_path in dso_networks:
    params = analyze_dso_network(net_path, adapt_network=True)
    results.append(params)

# Create validation report
df = pd.DataFrame(results)
df.to_excel('/data/validation_report.xlsx', index=False)
```

## Contributing

If you extend this functionality, please:
1. Add test cases for new zone mappings
2. Document any DSO-specific adaptations
3. Update this README with examples

## See Also

- `topology_analysis.py` - Core parameter calculation logic
- `utils.py` - Configuration and utility functions
- `config_validation.yaml` - Configuration file
- Original database-based workflow documentation

