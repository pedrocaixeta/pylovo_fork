# Grid Comparison Files

This directory now mainly contains the notebook and documentation for the grid-comparison workflow.

## Analysis Runner

The active comparison workflow now lives in `src/pylovo/analysis/comparison_helpers.py` and is invoked through the validation CLI in `src/pylovo/cli/validate.py`.
- **Input (Real)**: `LV_*.json` subnets from the configured `GRID_DATA_PATH`.
- **Input (Synthetic)**: grids for PLZ `91301` from the `pylovo` database.
- **Output**: `validation/metrics/real_grid_metrics.csv` and `validation/metrics/synthetic_grid_metrics.csv`.

## Active Notebook

### `validation/grid_comparison_notebook_v2.ipynb`
Current notebook for inspecting the exported comparison parameters.

## Usage

```bash
uv run pylovo-validate compare-grids

# Optional overrides
uv run pylovo-validate compare-grids --plz 91301 --output-dir validation/metrics
```

Superseded validation files are archived under `validation/old`.