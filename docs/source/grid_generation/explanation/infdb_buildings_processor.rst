InfDB Buildings Processor
=========================

Motivation
----------

The use of openly available infrastructure data provides a reliable foundation for developing tools in urban analysis and planning.
By integrating this data, it becomes possible to support a more detailed understanding of the built environment.

To manage and utilize complex 3D city models, InfDB incorporates 3DCityDBv5.
It supports the import of LoD2 datasets in the standardized CityGML format, enabling structured storage and retrieval of 3D geospatial data.
The models can be enriched with statistical data from census sources, and spatial context is further improved through integration with the Basemap Project.
Together, these components provide a flexible and scalable foundation for geospatial exploration, simulation, and infrastructure planning.
They are all built into InfDB direcly.

To make the above-mentioned data usable in Pylovo, it must first be combined into a single table:
``pylovo_input.buildings``.
This is the purpose of the processor in InfDB.

Data Sources
------------

The processor uses three InfDB data sources:

- `3DCityDBv5 <https://docs.3dcitydb.net/3dcitydb/>`_:
  Provides detailed 3D building models in Level of Detail 2 (LOD2), including roofs, walls, and building functions. Useful for visualization, simulation, and spatial analysis tasks.  

- `Census <https://ergebnisse.zensus2022.de/datenbank/online/>`_:
  Statistical data in 100m x 100m grids which ontains demographic and housing statistics from Zensus 2022, such as population density, household types, and age structure.

- `Basemap <https://basemap.de/data/produkte/web_vektor/anwendungsbeispiele/alkis-color.html>`_:  
  Basemap includes streets, parcels, land cover, and administrative features. Supports background mapping and street-level geometry extraction.  

3DCityDBv5 resides in the ``citydb`` schema. Census and Basemap are located in the ``opendata`` schema.

Column overview
---------------

An overview of the column sources and roles for ``pylovo_input.buildings`` is shown below:

+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| Column Name                  | Source                                                                   | Role                                                       |
+==============================+==========================================================================+============================================================+
| ``id``                       | ``citydb.feature.id``                                                    | Building ID                                                |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``objectid``                 | ``citydb.feature.objectid``                                              | Alternate unique ID (from citydb)                          |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``geom``                     | ``citydb.geometry_data.geometry``                                        | 2D geometry in EPSG:3035                                   |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``building_use_id``          | ``citydb.property.val_*``                                                | Internal ID for building use                               |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``building_use``             | ``citydb.property.val_*``                                                | One of ``Residential``, ``Industrial``,                    |
|                              |                                                                          | ``Commercial``, ``Public``                                 |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``floor_area``               | ``citydb.property.val_*``                                                | Ground floor area                                          |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``height``                   | ``citydb.property.val_*``                                                | Building height                                            |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``floor_number``             | ``citydb.property.val_*`` or estimated from ``height``                   | Number of floors                                           |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``construction_year``        | ``opendata.cns22_100m_baujahr_jz``                                       | Ranges: ``'-1919'``, ``'1919-1948'``,                      |
|                              |                                                                          | ``'1949-1978'``, ``'1979-1990'``, etc.                     |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``building_type``            | Derived from ``opendata.cns22_100m_wohnung_gbtyp_groesse``,              | ``AB``, ``MFH``, ``TH``, or ``SFH``                        |
|                              | plus ``height`` and ``floor_area``                                       |                                                            |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``occupants_per_building``   | ``opendata.cns22_100m_bevoelkerungszahl``                                | Estimated number of residents                              |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``households_per_building``  | ``opendata.cns22_100m_durchschn_haushaltsgroesse``                       | Estimated number of households                             |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``postcode``                 | ``opendata.plz_plz-5stellig.plz``                                        | Postcode based on building centroid                        |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+
| ``address_street_id``        | Derived from ``pylovo_input.ways`` and ``citydb.address``                | Street ID corresponding to the building's address          |
+------------------------------+--------------------------------------------------------------------------+------------------------------------------------------------+


Data Filling Process
--------------------

A short overview of the processing steps can be seen in the following visualization:

#. Create the ``buildings`` table.
#. Fill ``id``, ``objectid``, ``building_use``, ``building_use_id``, ``height``, ``floor_area``, and ``geom`` using CityDB.
#. Remove buildings that are too small to be considered as residential buildings.
#. Fill ``floor_number`` directly or estimate using building height and median floor heights of all buildings that have ``floor_number`` data.
#. Use CityDB, Census to fill ``occupants``, ``households``, and ``construction_year``. When Census data is missing the nearest grid with data to a building is used.
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
- Otherwise, estimate using median floor heights of grouped by type of all buildings that had ``storeysAboveGround`` data.

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

