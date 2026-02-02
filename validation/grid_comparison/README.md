# Grid Comparison Scripts

This directory contains scripts to validate Synthetic LV grids against Real DSO data.

## Scripts

### `compare_grids.py`
Main script to run the comparison.
- **Input (Real)**: JSON subnets from configured data path.
- **Input (Synthetic)**: Grids from `pylovo` database (PLZ 91301).
- **Process**:
    1. Preprocesses real grids (synthesizes dummy trafo, estimates loads).
    2. Calculates metrics using `pylovo.analysis.parameter_calculation.ParameterCalculator`.
    3. Aggregates results into `results/comparison_metrics.csv`.
    4. Generates boxplots in `results/`.
- **Usage**:
    ```bash
    uv run pylovo-validate compare-grids
    # OR
    uv run python validation/grid_comparison/compare_grids.py
    ```