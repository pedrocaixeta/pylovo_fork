The Database Architecture of Pylovo
===================================

.. image:: ../../images/database/database_diagram.png
    :width: 100%
    :alt: Default view

The database follows a hierarchical structure:

1. **Postal Code Level** (``postcode_result``) - Top-level geographical organization
2. **Grid Cluster Level** (``grid_result``) - Individual grids within postal codes
3. **Building Level** (``buildings_result``) - Individual buildings and consumers
4. **Infrastructure Level** - Lines, transformers, and equipment

Data source tables
------------------

**postcode** - Contains postal code information. Used for determining a boundaries of a postal code.

**municipal_register** - Municipal administrative data linked to postcodes. Used to determine which postcode belongs to which ags.

**res (Residential Buildings)** - Residential building data table used for importing residential buildings.

**oth (Other Buildings)** - Non-residential buildings with simplified structure used for importing non-residential buildings.

**ways** - Street data is imported here.

**equipment_data** - Electrical equipment specifications and costs, directly imported from a CSV-file.

**transformers** - Transformer infrastructure from OpenStreetMap data.

**consumer_categories** - Defines different types of electrical consumers with their load characteristics, also from a CSV-file.

**ags** - Logs which ags region buildings have been imported into the database.

Version Control and Configuration
---------------------------------

**version** - Tracks versions in the database so that the same grid can be generated across different versions for example.

**classification_version** - Tracks different classification versions.

Result Tables
-------------

**postcode_result** - Each grid generation generates multiple grids in a postcode.

**grid_result** - A grid result row uniquely identifies a generated grid.

**buildings_result** - Buildings relevant to a grid are stored here.

**ways_result** - Ways that are part of a grid.

**lines_result** - Electrical lines of a grid.

Classification
--------------

**sample_set** - Stores sampled data for classification algorithms.

**transformer_classified** - Results of transformer clustering analysis using multiple algorithms.

Parameter Storage
-----------------

**clustering_parameters** - Detailed clustering analysis parameters for each grid result.

**plz_parameters** - Parameters at postal code level stored as JSON.

Views
-----

The schema includes several views that combine data across tables:

- **transformer_positions_with_grid**: Transformer positions with grid cluster context.
- **transformer_classified_with_grid**: Classification results with grid cluster context.
- **buildings_result_with_grid**: Building results with grid cluster context.
- **lines_result_with_grid**: Line results with grid cluster context.

Spatial Data
------------

- All geometric data uses EPSG:3035 coordinate reference system
- Supports both point and polygon geometries for different feature types

Foreign Key Constraints
-----------------------

- Comprehensive referential integrity through CASCADE DELETE
- Ensures data consistency across related tables
- Supports clean version management
