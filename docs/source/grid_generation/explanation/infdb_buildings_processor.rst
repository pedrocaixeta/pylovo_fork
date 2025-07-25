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
  Provides detailed 3D building models in Level of Detail 2 (LOD2), including roofs, walls, and building functions.
  Useful for visualization, simulation, and spatial analysis tasks.

- `Census <https://ergebnisse.zensus2022.de/datenbank/online/>`_:
  Statistical data in 100m x 100m grids which ontains demographic and housing statistics from Zensus 2022, such as population density, household types, and age structure.

- `Basemap <https://basemap.de/data/produkte/web_vektor/anwendungsbeispiele/alkis-color.html>`_:  
  Basemap includes streets, parcels, land cover, and administrative features.
  Supports background mapping and street-level geometry extraction.
 

3DCityDBv5 resides in the ``citydb`` schema.
Census and Basemap are located in the ``opendata`` schema.

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


Processing Steps
----------------

This section outlines the full data filling and processing flow for building data, combining building geometries and census data.

Create the Buildings Table
~~~~~~~~~~~~~~~~~~~~~~~~~~

We begin by creating the ``pylovo_input.buildings`` table, which will hold all relevant attributes for each structure.
Using CityDB, we populate ``id``, ``objectid``, ``building_use_id``, and ``building_use`` (mapped to from ``building_use_id``).
Only buildings with function codes starting with ``31001_`` are loaded.
Garages (``31001_2463``) and water tanks (``31001_2513``) are excluded.

Import and Filter Geometry
~~~~~~~~~~~~~~~~~~~~~~~~~~

Geometry is linked to ground surfaces via the ``objectid`` and converted into EPSG:3035.
The ``floor_area`` can also be extracted from the ground surface features.
Any building smaller than 12 m² is filtered out, as such structures are assumed to be non-habitable.
After ``height`` is imported from ``citydb`` buildings shorter than 3.5 meters are filtered out. 

Fill and Estimate Floor Numbers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``floor_number`` is taken from the ``storeysAboveGround`` attribute when available.
If it's missing, we estimate it by dividing the total building height by the median height per floor.
These medians are calculated from buildings where floor numbers were known and grouped by type to reflect realistic patterns.

Estimate Occupancy and Households
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Only residential buildings proceed to this step.
We estimate the number of occupants by distributing census population data proportionally based on each building's volume (``floor_area * height``).
Households are then estimated using the average household size from census.
Every residential building is enforced to have at least one occupant and one household.
If census data is missing, the nearest census grid with data is used to fill in the values.

Assign Construction Year
~~~~~~~~~~~~~~~~~~~~~~~~

Construction years are assigned randomly but weighted by the corresponding census grid data.
Again, for buildings where the construction year is missing, we find the nearest grid with available data and assign based on those distributions.

Count Touching Neighbors
~~~~~~~~~~~~~~~~~~~~~~~~

To support building type classification, we identify neighboring buildings.
Structures within 0.01 meters are considered "touching".
Each building is assigned a neighbor count.
Zero neighbors are allowed.
This is used for assignin building types.

Classify Building Type
~~~~~~~~~~~~~~~~~~~~~~

Buildings are initially classified based on structural characteristics and neighborhood context.
The following initial classification rules are applied:

- Apartment Blocks (AB) are defined as buildings with 4 or more floors, or those with 3+ floors and 3+ touching neighbors, or those with a floor area above 1500 m².

- Single-Family Homes (SFH) are smaller buildings with under 350 m², up to 3 floors, and no touching neighbors.
  Extremely small homes (under 200 m²) with ≤2 floors and fewer than 2 touching neighbors also qualify.

- Townhouses (TH) fall in the range of 80-150 m², have 2-3 floors, 1-2 touching neighbors, and similar size (±20%) to neighboring buildings.

- Multi-Family Homes (MFH) have 2-3 floors or are buildings over 150 m² with 1-3 touching neighbors.

Types are recursively propagated to touching neighbors when patterns match.
Buildings that touch an AB become AB.
Buildings that touch an SFH and have an area of less than 100 m² and ≤2 floors become SFH.
Buildings touching at least 2 THs with 25% floor area discrepancy become TH.
Buildings touching 1 TH with 20% floor area discrepancy become TH.
Buildings with 2-3 floors touching MFH likely also MFH.
If classification fails but the building is residential, it defaults to AB.
This classification is then refined using household counts: one household implies SFH or TH, two to four households point to MFH, and five or more households suggest AB.

Rebalance to Match Census
~~~~~~~~~~~~~~~~~~~~~~~~~

Once initial classification is complete, building type distributions are adjusted per census grid to match target proportions.
Rebalancing follows a set of conversion rules:

- To increase AB, convert the largest MFH or TH.
- To raise MFH numbers, convert the largest TH or smallest AB.
- To increase TH, convert smaller MFHs.
- To boost SFH, convert smaller TH or MFHs.

Household counts are kept consistent during these adjustments.

Final Attribute Assignments
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Postcodes are assigned using PLZ geometry overlays.
Finally, ``address_street_id`` is linked using matching address data from buildings and ways.
This field can be null if no address match is found.
