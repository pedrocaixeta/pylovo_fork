# Grid Creation Scripts

This directory contains scripts for creating electrical grids using the Pylovo framework.

## Unified Grid Creation

### `create_grids.py`

This is the main script for grid creation that handles all scenarios based on configuration settings. It replaces the previous separate scripts for single PLZ, multiple PLZ, and AGS-based grid creation.

#### Usage

```bash
python runme/create/create_grids.py
```

#### Configuration

The script behavior is controlled by settings in three separate configuration files:

1. **`config/config_database.yaml`**: Database connection settings
2. **`config/config_grid.yaml`**: Grid generation parameters and regional configuration
3. **`config/config_analysis.yaml`**: Analysis, plotting, and municipal register settings

**Regional Scale Options:**
- `postcode`: Work at postcode level using PLZ codes
- `municipality`: Work at municipality level using AGS codes

**Input Types:**
- **Single area**: Provide a single integer (e.g., `PLZ: 80331` or `AGS: 9162000`)
- **Multiple areas**: Provide a list of integers (e.g., `PLZ: [80331, 80333, 80797]` or `AGS: [9162000, 9163000]`)

#### Examples

1. **Single Postcode** (in `config/config_grid.yaml`): 
   ```yaml
   REGIONAL_SCALE: postcode
   PLZ: 80331
   ```

2. **Multiple Postcodes** (in `config/config_grid.yaml`): 
   ```yaml
   REGIONAL_SCALE: postcode
   PLZ: [80331, 80333, 80797, 80799, 80805]
   ```

3. **Single Municipality** (in `config/config_grid.yaml`): 
   ```yaml
   REGIONAL_SCALE: municipality
   AGS: 9162000
   ```

4. **Multiple Municipalities** (in `config/config_grid.yaml`): 
   ```yaml
   REGIONAL_SCALE: municipality
   AGS: [9162000, 9163000, 9164000]
   ```

**Note**: Only specify either `PLZ` or `AGS` based on your chosen regional scale. The script will automatically determine whether to run single or multiple grid generation based on whether you provide a single integer or a list.

#### Features

- Unified interface for all grid creation scenarios
- Regional scale selection (postcode vs municipality level)
- Automatic execution mode detection based on input type
- Configuration-driven execution
- Comprehensive error handling and timing
- Support for both INFDB and local database modes
- Optional plotting capabilities
- Parallel processing support for multiple area scenarios

## Migration from Old Scripts

The following old scripts have been replaced by `create_grids.py`:

- ~~`create_grid_single_plz.py`~~ → Use `create_grids.py` with `REGIONAL_SCALE: postcode` and `PLZ: 80331`
- ~~`create_grid_multi_plz.py`~~ → Use `create_grids.py` with `REGIONAL_SCALE: postcode` and `PLZ: [80331, 80333, 80797]`
- ~~`create_grid_ags.py`~~ → Use `create_grids.py` with `REGIONAL_SCALE: municipality` and `AGS: 9162000`

## Configuration Files

Configuration is now organized into three logical files:

### `config/config_database.yaml`
- Database connection settings
- InfDB configuration
- .env file guidance for sensitive credentials

### `config/config_grid.yaml`
- Grid generation parameters
- Regional configuration (PLZ/AGS settings)
- Equipment data and thresholds
- Clustering parameters
- Voltage properties

### `config/config_analysis.yaml`
- Plotting configuration
- Municipal register column definitions
- Analysis settings
