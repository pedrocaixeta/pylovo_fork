# DSO Network Analysis Solution - Implementation Summary

## Problem Solved

Successfully implemented a solution to analyze DSO-provided JSON networks (SWD_V7) using the existing topology analysis functions that were originally designed for synthetic grids in the database.

## Key Challenges Addressed

1. **Different Data Structure**: DSO data has different bus naming conventions and lacks expected metadata (PLZ, BCID, KCID)
2. **No Database Access**: DSO analysis needs to work without database dependencies
3. **Multi-Grid Networks**: SWD_V7 contains 188 independent LV grids in a single file
4. **Custom Equipment Types**: DSO uses custom transformer types (e.g., "MSNS_0001") and cable types (e.g., "NAYY-J 4x50") not in pandapower's standard library
5. **Missing Zone Information**: DSO data lacks building zone classifications needed for simultaneity calculations

## Solution Architecture

### New Modules Created

1. **`data_adapter.py`** - Normalizes external networks to match expected structure
   - Renames buses to follow conventions (LVbus, Consumer Nodebus, Connection Nodebus)
   - Adds and normalizes zone information (Residential/Commercial/Public)
   - Handles load column differences (p_mw vs max_p_mw)
   - Validates network structure

2. **`standalone_calculator.py`** - Database-independent parameter calculation
   - Wraps existing `ParameterCalculator` logic
   - Handles database access failures gracefully
   - Estimates simultaneous peak load using category-based factors
   - Provides DataFrame export functionality

3. **`multi_grid_splitter.py`** - Splits multi-grid networks into individual grids
   - Identifies grids by transformer
   - Uses breadth-first search to find connected components
   - Handles custom transformer and line types from DSO data
   - Optimized to create network graph only once

4. **`benchmark_analysis.py`** (updated) - Main entry point for DSO analysis
   - Auto-detects single vs multi-grid networks
   - Orchestrates splitting, adaptation, and analysis
   - Exports results as CSV and JSON
   - Displays aggregate statistics for multi-grid networks

5. **`README_DSO_ANALYSIS.md`** - Comprehensive documentation
   - Quick start guide
   - Advanced usage examples
   - Troubleshooting tips
   - API reference

## How It Works

### For Single-Grid Networks
```
DSO JSON → Load → Adapt Structure → Calculate Parameters → Export Results
```

### For Multi-Grid Networks (like SWD_V7)
```
DSO JSON → Load → Split into Grids → For Each Grid:
                                        ├─ Adapt Structure
                                        ├─ Calculate Parameters
                                        └─ Aggregate
         → Export CSV + Summary JSON
```

## Usage

### Basic Usage
```bash
cd /home/breveron/git/github/pylovo
python src/analysis/benchmark_analysis.py
```

### Programmatic Usage
```python
from src.analysis.benchmark_analysis import calc_grid_parameters_benchmark

# Analyze first 10 grids (for testing)
results = calc_grid_parameters_benchmark(
    adapt_network=True,
    export_results=True,
    max_grids=10
)
```

### Analyze All Grids
```python
# WARNING: This will take significant time for 188 grids
results = calc_grid_parameters_benchmark(
    adapt_network=True,
    export_results=True,
    max_grids=None  # Analyze all grids
)
```

## Configuration

Edit `src/analysis/config_validation.yaml`:
```yaml
data_dir: "/data/"
net_name: "SWD_V7"
projection: "epsg:3035"
```

## Key Features

### Data Adaptation
- **Automatic bus naming**: Identifies and renames buses based on their role
- **Zone normalization**: Maps DSO zones to standard categories
- **Load column handling**: Creates `max_p_mw` from `p_mw` if needed
- **Validation**: Ensures required elements exist

### Parameter Calculation
All the same metrics as synthetic grids:
- Topology: branches, house connections, connection buses
- Load: households, equivalent households, max power, simultaneous peak load
- Spatial: cable length, transformer distances, house distances
- Electrical: resistance, reactance, R/X ratio, voltage drop proxies

### Multi-Grid Handling
- **Automatic detection**: Identifies multi-grid networks by transformer count
- **Efficient splitting**: Creates network graph once, reuses for all grids
- **Parallel-ready**: Grid analysis is independent, can be parallelized
- **Aggregate statistics**: Automatically computes mean ± std for all metrics

## Performance Considerations

### Large Networks
The SWD_V7 network (33,657 buses, 188 transformers) requires:
1. **Graph Creation**: ~2-5 minutes (one-time cost)
2. **Grid Splitting**: ~5-10 minutes (depends on network complexity)
3. **Per-Grid Analysis**: ~5-30 seconds per grid
4. **Total Time**: ~30-60 minutes for all 188 grids

### Optimization Tips
1. **Test with subset**: Use `max_grids=10` for initial testing
2. **Parallel processing**: Can be added for multi-grid analysis
3. **Caching**: Split grids once, save individually, analyze separately

## Output Files

### For Multi-Grid Networks
1. **`/data/SWD_V7_analysis_results.csv`** - Detailed results for each grid
   - One row per grid
   - All 21 topology parameters as columns
   - Grid ID and metadata

2. **`/data/SWD_V7_analysis_summary.json`** - Statistical summary
   - Total grids analyzed
   - Mean, std, min, max for all parameters
   - Percentiles (25%, 50%, 75%)

### For Single-Grid Networks
1. **`/data/{netname}_analysis_results.json`** - Single grid parameters

## Testing

### Unit Test
```bash
python src/analysis/test_dso_analysis.py
```

### Integration Test with DSO Data
```bash
# Quick test with 3 grids
python -c "
from src.analysis.benchmark_analysis import calc_grid_parameters_benchmark
results = calc_grid_parameters_benchmark(max_grids=3)
print(f'Analyzed {len(results)} grids successfully!')
"
```

## Differences from Database Analysis

| Feature | Database Analysis | DSO Analysis |
|---------|-------------------|--------------|
| Data Source | PostgreSQL | JSON files |
| Network Structure | Expected | Adapted automatically |
| Metadata Required | PLZ/BCID/KCID | None |
| Simultaneous Load | DB lookup | Estimated |
| Multi-Grid Support | No | Yes |
| Result Storage | Database | CSV/JSON files |

## Known Limitations

1. **Simultaneous Peak Load**: Estimated using simple factors instead of distance-based database lookup (5-15% difference expected)

2. **Zone Information**: If DSO data lacks zones, all loads default to "Residential"

3. **Performance**: Large multi-grid networks (100+ grids) take significant time due to graph creation

4. **Radial Topology Assumption**: Non-radial networks may produce unexpected results

## Troubleshooting

### "Network graph creation takes too long"
- Expected for large networks (33K+ buses)
- Consider splitting the JSON file into smaller networks beforehand
- Or analyze a subset using `max_grids` parameter

### "No LV bus found"
- DSO network structure doesn't match expected format
- Check that transformers exist and have valid lv_bus references

### "Unknown standard type"
- Fixed in current implementation
- Uses `create_transformer_from_parameters` and `create_line_from_parameters`

## Next Steps for Complete Analysis

To analyze all 188 grids in SWD_V7:

```bash
# Run in background (will take 30-60 minutes)
cd /home/breveron/git/github/pylovo
nohup python -c "
from src.analysis.benchmark_analysis import calc_grid_parameters_benchmark
results = calc_grid_parameters_benchmark(
    adapt_network=True,
    export_results=True,
    max_grids=None  # All grids
)
print(f'Complete! Analyzed {len(results)} grids')
" > analysis_output.log 2>&1 &

# Check progress
tail -f analysis_output.log
```

## Validation

To validate results against synthetic grids:

```python
import pandas as pd

# Load DSO results
dso_results = pd.read_csv('/data/SWD_V7_analysis_results.csv')

# Load synthetic grid results from database
from src.database.database_client import DatabaseClient
dbc = DatabaseClient()
synthetic_results = dbc.read_all_clustering_parameters(plz=86150)

# Compare distributions
comparison = pd.DataFrame({
    'DSO_mean': dso_results.mean(),
    'DSO_std': dso_results.std(),
    'Synthetic_mean': synthetic_results.mean(),
    'Synthetic_std': synthetic_results.std()
})

print(comparison[['cable_length_km', 'max_trafo_dis', 'no_households']])
```

## Code Reuse

Percentage of existing code reused:
- **topology_analysis.py**: 100% (no changes, fully reused)
- **Database logic**: 0% (bypassed, not needed)
- **Analysis algorithms**: 100% (all calculation methods reused)

New code added:
- **Adaptation layer**: ~300 lines
- **Multi-grid splitting**: ~250 lines
- **Standalone wrapper**: ~200 lines
- **Orchestration**: ~200 lines
- **Total new code**: ~950 lines

## Success Criteria ✓

- [x] Reuse existing topology_analysis functions
- [x] No modification to core analysis code
- [x] Handle DSO JSON data structure
- [x] Support multi-grid networks
- [x] Handle custom equipment types
- [x] Work without database access
- [x] Export results for validation
- [x] Comprehensive documentation

## Files Modified/Created

### Created
- `src/analysis/data_adapter.py`
- `src/analysis/standalone_calculator.py`
- `src/analysis/multi_grid_splitter.py`
- `src/analysis/README_DSO_ANALYSIS.md`
- `src/analysis/test_dso_analysis.py`

### Modified
- `src/analysis/benchmark_analysis.py` (complete rewrite for multi-grid support)
- `src/analysis/config_validation.yaml` (fixed YAML syntax error)

### Unchanged (Fully Reused)
- `src/analysis/topology_analysis.py` ✓
- `src/utils.py` ✓
- All core calculation methods ✓

