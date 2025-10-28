# Plot All Subgrids on Single Map - Quick Guide

Create a single interactive map showing all LV subgrids together, color-coded by network.

## Quick Examples

### 1. Plot All 151 Grids
```bash
python src/analysis/validation/plot_all_on_map.py
```

**Result**: Creates `grid_data/subgrids/all_grids_map.html` with all networks

### 2. Plot Top 20 Largest Grids
```bash
python src/analysis/validation/plot_all_on_map.py --top 20
```

### 3. Plot Only Large Grids
```bash
python src/analysis/validation/plot_all_on_map.py --filter-size Large
```

### 4. Custom Output File
```bash
python src/analysis/validation/plot_all_on_map.py --top 50 --output my_map.html
```

### 5. Filter by Branches
```bash
python src/analysis/validation/plot_all_on_map.py --min-branches 10 --max-branches 25
```

## Map Features

### What You See
- 🔴 **Red Stars**: Transformer locations
- 🌈 **Colored Lines**: Each network has a unique color
- 🔵 **Small Dots**: Buses (color matches network)
- 📊 **Interactive Legend**: Click to show/hide networks

### Interactions
- **Hover** over transformers to see grid details (branches, buses, loads)
- **Hover** over buses to see which grid they belong to
- **Click legend** to toggle network visibility
- **Pan/Zoom** to explore different areas
- **Double-click** to reset view

## Output Details

### File Size
- Top 20 grids: ~5-10 MB
- All 151 grids: ~30-50 MB (depending on density)

### Performance
- Loading time: 1-2 minutes for all grids
- Browser rendering: Fast with modern browsers
- Smooth pan/zoom even with thousands of elements

## Use Cases

### 1. Overview of All Networks
```bash
python src/analysis/validation/plot_all_on_map.py
```
**Use for**: Understanding spatial distribution, identifying clusters

### 2. Compare Large Urban Networks
```bash
python src/analysis/validation/plot_all_on_map.py --filter-size Large
```
**Use for**: Analyzing complex networks, comparing topologies

### 3. Regional Analysis
```bash
python src/analysis/validation/plot_all_on_map.py --top 30
```
**Use for**: Focusing on major networks, validation work

### 4. Size-Based Comparison
```bash
python src/analysis/validation/plot_all_on_map.py --min-branches 15
```
**Use for**: Medium-to-large grids only

## Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--top N` | Top N largest grids | `--top 20` |
| `--filter-size` | By size (Tiny/Small/Medium/Large) | `--filter-size Large` |
| `--min-branches` | Minimum branches | `--min-branches 10` |
| `--max-branches` | Maximum branches | `--max-branches 25` |
| `--output` | Custom output file | `--output my_map.html` |

## Tips

1. **Start with --top 20** to get a quick overview
2. **Use legend** to toggle specific networks on/off
3. **Large networks** (all 151) take 1-2 min to generate but work fine
4. **Color coding** helps identify individual networks
5. **Hover over transformers** for detailed stats

## Troubleshooting

**Map is slow**
- Filter to fewer grids with `--top` or `--filter-size`
- Use a modern browser (Chrome/Firefox recommended)

**Missing grids**
- Some grids may not have geodata (script skips them)
- Check console output for which grids loaded

**Can't see small networks**
- Zoom in to see smaller grids
- Use legend to hide large networks temporarily

## Examples

### Urban Analysis
```bash
# All large grids on one map
python src/analysis/validation/plot_all_on_map.py --filter-size Large --output urban_grids.html
```

### Validation Set
```bash
# Top 50 for DSO comparison
python src/analysis/validation/plot_all_on_map.py --top 50 --output validation_set.html
```

### Complete Archive
```bash
# All 151 grids
python src/analysis/validation/plot_all_on_map.py --output complete_map.html
```

## What's Included

For each network:
- ✅ Transformer location (red star)
- ✅ All buses (colored dots)
- ✅ All lines (colored lines)
- ✅ Hover tooltips with info
- ✅ Legend entry for show/hide

## Performance Stats

| Grids | Load Time | File Size | Rendering |
|-------|-----------|-----------|-----------|
| 5 | ~10 sec | ~5 MB | Instant |
| 20 | ~30 sec | ~15 MB | Fast |
| 50 | ~1 min | ~25 MB | Good |
| 151 | ~2 min | ~40 MB | Smooth |

---

**Ready to visualize!** Start with `--top 20` to get a feel for the map, then run with all grids for the complete overview.

