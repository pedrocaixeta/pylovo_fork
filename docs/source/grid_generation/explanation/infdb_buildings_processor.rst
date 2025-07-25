InfDB Buildings Processor
=========================

To make buildings data from InfDB usable in Pylovo, it must first be combined into a single table:
``pylovo_input.buildings``.
This is the role of the processor in InfDB.

Data Sources
------------

The processor uses three InfDB data sources:

- **3DCityDBv5**: Building data
- **Census**: Statistical data in 100m x 100m grids
- **Basemap**: Mainly used for processing streets

3DCityDBv5 resides in the ``citydb`` schema. Census and Basemap are located in the ``opendata`` schema.

A visual overview of the column sources for ``pylovo_input.buildings`` is shown below:

.. image:: ../../images/infdb/buildings_sources.jpg
    :width: 100%
    :alt: Data sources

- ``id``: From ``citydb.feature.id``
- ``objectid``: From ``citydb.feature.objectid``
- ``geom``: From ``citydb.geometry_data.geometry``
- ``building_use_id``, ``building_use``, ``floor_area``, ``height``: From ``citydb.property.val_*``
- ``floor_number``: From ``citydb.property.val_*`` or estimated from ``height`` if missing
- ``construction_year``: From ``opendata.cns22_100m_baujahr_jz``
- ``building_type``: Derived from ``opendata.cns22_100m_wohnung_gbtyp_groesse`` plus ``height`` and ``floor_area``
- ``occupants_per_building``: From ``opendata.cns22_100m_bevoelkerungszahl``
- ``households_per_building``: From ``opendata.cns22_100m_durchschn_haushaltsgroesse``
- ``postcode``: From ``opendata.plz_plz-5stellig.plz``

Column Roles
------------

- **id**: Building ID
- **objectid**: Alternate unique ID (from citydb)
- **geom**: 2D geometry in EPSG:3035
- **building_use_id**: Internal ID for building use
- **building_use**: One of ``Residential``, ``Industrial``, ``Commercial``, ``Public``
- **floor_area**: Ground floor area
- **height**: Building height
- **floor_number**: Number of floors
- **construction_year**: Can be ranges ``'-1919'``, ``'1919-1948'``, ``'1949-1978'``, ``'1979-1990'``, ``'1991-2000'``, ``'2001-2010'``, ``'2011-2019'`` or ``'2020-'``
- **building_type**: ``AB``, ``MFH``, ``TH``, or ``SFH``
- **occupants_per_building**: Estimated number of residents
- **households_per_building**: Estimated number of households
- **postcode**: Postcode based on building centroid

Data Filling Process
--------------------

An overview of the processing steps can be seen in the following visualization:

.. image:: ../../images/infdb/buildings_steps.jpg
    :width: 100%
    :alt: Processing steps

#. Create the ``buildings`` table.
#. Fill ``id``, ``objectid``, ``building_use``, ``building_use_id``, ``height``, ``floor_area``, and ``geom`` using CityDB.
#. Remove buildings that are too small to reasonably use electricity.
#. Fill ``floor_number`` directly or estimate using building height and median floor heights.
#. Use CityDB, Census, and nearest-grid data to fill ``occupants``, ``households``, and ``construction_year``.
#. Classify ``building_type`` using ``floor_number``, ``floor_area``, and neighbor analysis.
#. Fix inconsistencies, e.g., SFHs must have only one household.
#. Rebalance ``building_type`` distribution to match census data.
#. Assign postcodes using PLZ geometry.
#. Assign ``address_street_id`` using addresses from buildings and ways (nullable).

Assumptions
-----------

Building Size
~~~~~~~~~~~~~

- Buildings under 12 m² or 3.5 m tall are excluded (likely not habitable or consuming power).

Spatial Relationships
~~~~~~~~~~~~~~~~~~~~~

- Buildings within 0.01 meters are considered "touching" and used in type propagation.
- Census grid assignment is based on centroid location.

Occupancy & Household Distribution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Residents are distributed by volume (``floor_area * height``).
- Households estimated using average census household size.
- Minimum: 1 occupant and 1 household for residential buildings.
- SFH = 1 household, MFH = 2–4, AB = 5+.

Construction Year Assignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Census-based weighted random assignment of construction years.
- Missing values filled using the nearest census grid.

Initial Building Type Classification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **AB**: 4+ floors, or 3+ floors + 3+ neighbors, or floor area > 1500 m²
- **SFH**: <350 m² + ≤3 floors + no neighbors, or <200 m² + ≤2 floors + <2 neighbors
- **TH**: 80–150 m², 2–3 floors, 1–2 neighbors, similar size to neighbors (±20%)
- **MFH**: 2–3 floors, or >150 m² + 1–3 neighbors

Processing Steps
----------------

Initial Data Import and Filtering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Load only buildings (codes starting with ``31001_``).
- Exclude garages (``31001_2463``) and water tanks (``31001_2513``).
- Map function codes to building uses.

Height Processing
~~~~~~~~~~~~~~~~~

- Extract height from nested ``val_*`` fields.
- Filter out buildings under 3.5m.

Geometry and Floor Area
~~~~~~~~~~~~~~~~~~~~~~~

- Match buildings to ground surfaces via ``objectid``.
- Convert to EPSG:3035.
- Filter out buildings under 12 m².

Floor Number Estimation
~~~~~~~~~~~~~~~~~~~~~~~

- Extract from ``storeysAboveGround`` if available.
- Otherwise, estimate using typical floor heights by type.

Touching Neighbors
~~~~~~~~~~~~~~~~~~

- Create a view of buildings within 0.01 meters.
- Count neighbors (zero allowed).

Occupancy Estimation
~~~~~~~~~~~~~~~~~~~~

- Distribute census population by building volume.
- Estimate households using average household size.
- Apply only to residential buildings.
- Fill gaps with nearest grid that has data.

Construction Year Assignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Use census data distributions to assign year ranges.
- Assign missing values from nearest grid with data.

Building Type Classification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Classify based on the assumptions listed above.
- Propagate types to neighbors when similar.
- Default unclassified residential buildings to AB.
- Refine types using household counts:

  - 1 household → SFH or TH
  - 2–4 households → MFH
  - 5+ → AB

- Rebalance to match census targets per grid:

  - AB up: Convert largest MFH or TH
  - MFH up: Convert largest TH or smallest AB
  - TH up: Convert smaller MFH
  - SFH up: Convert smaller TH or MFH

- Maintain consistency in household counts.

Final Augmentations
~~~~~~~~~~~~~~~~~~~

- Assign postcode from PLZ geometry.
- Assign street ID from address (nullable).

