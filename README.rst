.. image:: docs/source/images/logo.png
    :width: 700
    :alt: Default view

**A repo to generate synthetic low-voltage distribution grids based on open data.**

.. list-table::
   :widths: auto

   * - License
     - |badge_license|
   * - Documentation
     - |badge_documentation|


**pylovo (PYthon tool for LOw-VOltage distribution grid generation)**
============

**Overview**
------------

pylovo is a Python-based tool for generating synthetic low-voltage (LV) distribution grids using open data sources. 
Designed for energy system modeling research, it generates realistic and analyzable grid models for user-defined geographic areas.
This enables researchers and practitioners to explore critical questions of the energy transition—such as the analysis
of the potential integration of distributed energy resources and how their flexibilities can be leveraged while accounting
for electricity grid constraints.


**Key Features**
------------

* **Synthetic Grid Generation**: Creates realistic LV distribution network topologies (transformers, feeder cables, house connections, ...) based on available geodata
* **Comprehensive Data Preprocessing**: Uses a reproducible and scalable preprocessing pipeline using harmonized open datasets (see section "Data Sources & Preprocessing Pipeline")
* **Geospatial Processing**: Utilizes PostgreSQL databases with PostGIS for efficient geographic data handling
* **Power System Integration**: Provides grid models in the format of existing simulation frameworks (Default: pandapower, WiP: OpenDSS)
* **Automated Analysis**: Provides comprehensive grid statistics and performance metrics for evaluating the generated networks
* **Visualization Support**: Includes tools for grid visualization and analysis using QGIS and geopandas

**Regional Coverage**
------------
* The default data currently supports all regions of Bavaria (extending to full Germany within the running `NEED <https://need.energy/>`_ project)
* Other countries can be added by two steps:

  1. Add an input data preprocessing pipeline for the respective country (e.g., see a parallel project working on the `US-pipeline <https://github.com/DAI-Lab/Gridtracer>`_).
  2. Adjust parameters in the ``config_generation.yaml`` file to consider specific equipment or grid dimensioning strategies across different countries.

**Data Sources & Preprocessing Pipeline**
------------
pylovo leverages a reproducible and scalable open-data-based preprocessing pipeline within a dockerized environment that integrates multiple harmonized datasets into a unified Infrastructure Database (`InfDB <https://github.com/tum-ens/InfDB>`_):

Main data sources:
* **3D Building Models (LoD2)**: High-resolution 3D building geometries as a base of various other data modeling tools
* **Census Demographics (Zensus 2022)**: Official statistical data on the population, households and buildings
* **Cadastral Geodata**: Official street networks with addresses and administrative boundaries
* **OpenStreetMap (OSM)**: Transformer locations and additional street network data

Main processing steps for pylovo:
* **Building Type Classification**: Building type allocation based on geometry and demographic data
* **Household Allocation**: Statistical assignment of households to buildings
* **Street Graph Construction**: Network routing consistent with cadastral information for realistic grid topology

**Installation**
------------

**Requirements**: Python 3.12+, Ubuntu WSL2 or Linux-based OS, Docker (for InfDB preprocessing)

.. code-block:: bash

   # Clone the repository
   git clone https://github.com/tum-ens/pylovo.git
   cd pylovo

   # Install dependencies
   uv sync
   # OR
   pip install -e .

   # Configure environment
   cp .env.example .env
   nano .env  # Add your database credentials

**Note:** The repository includes configuration templates in ``config/``, an ``.env.example`` file, and example data structures in ``raw_data/`` that are essential for running pylovo.

**User Data Requirements**
------------

Pylovo requires user-provided geospatial data in the ``raw_data/`` directory:

* **Building shapefiles**: Place building geometries (as ``.shp`` files) in ``raw_data/buildings/``. Files should be named with AGS codes (e.g., ``09162000.shp`` for a specific municipality). These are typically obtained from official cadastral sources or InfDB preprocessing.

* **Street network SQL**: Place the OSM-derived street network SQL file (``ways_public_2po_4pgr.sql``) in ``raw_data/ways/``. This file is generated using the `osm2po <http://osm2po.de/>`_ tool from OpenStreetMap data.

* **Transformer data** (optional): Automatically fetched from OpenStreetMap when running ``pylovo-setup``, or can be manually added to ``raw_data/transformer_data/``.

**Note**: When using InfDB, building and household data are fetched directly from the database, reducing the need for local shapefiles.

**Quick Start**
------------

1. **Setup InfDB** (preprocessing pipeline): Follow the `InfDB <https://github.com/tum-ens/InfDB>`_ "Getting Started" guide to set up the database on your machine. Start the preprocessing docker: ``docker compose -f tools/infdb-basedata/compose.yml up``

2. **Configure pylovo**: Copy ``.env.example`` to ``.env`` and add your database credentials from InfDB setup. Update ``config/config_generation.yaml`` with your target region (PLZ or AGS).

.. code-block:: bash

   cp .env.example .env
   nano .env  # Add your database credentials
   nano config/config_generation.yaml  # Set your region

3. **Setup pylovo database**: Run ``pylovo-setup`` to create database schema and import municipal register data.

4. **Generate grids**: Run ``pylovo-generate`` to create synthetic LV distribution grids for your configured region.

5. **Analyze results** (optional): Use ``pylovo-analyze`` for grid statistics and ``pylovo-export`` for QGIS visualization.

**Available Commands**

.. code-block:: bash

   pylovo-setup      # Create and populate database
   pylovo-generate   # Generate synthetic grids
   pylovo-classify   # Run grid classification (experimental)
   pylovo-analyze    # Analyze generated grids
   pylovo-delete     # Delete grids or data from database
   pylovo-export     # Export grids to QGIS format
   pylovo-import     # Import transformers from OSM
   pylovo-validate   # Validate configuration

For detailed usage: ``pylovo-<command> --help``

This setup ensures access to the full preprocessing pipeline with 3D building models, census data, and cadastral information for enhanced accuracy in grid generation.

**Scientific Background**
------------

For detailed methodology, see: `Reveron Baecker et al. (2025): Generation of low-voltage synthetic grid data for energy system modeling with the pylovo tool <https://doi.org/10.1016/j.segan.2024.101617>`_

License
====================
| The code of this repository is licensed under the **MIT License** (MIT).
| See `LICENSE.txt <LICENSE.txt>`_ for rights and obligations.
| Copyright: `pylovo <https://github.com/tum-ens/pylovo/>`_ © `TUM ENS`_ | `MIT <LICENSE.txt>`_

Citation
====================
| If you use this code in a scientific publication, please cite the following publication:
* Reveron Baecker et al. (2025): `Generation of low-voltage synthetic grid data for energy system modeling with the pylovo tool <https://doi.org/10.1016/j.segan.2024.101617>`_


.. |badge_license| image:: https://img.shields.io/github/license/tum-ens/pylovo
    :target: LICENSE.txt
    :alt: License

.. |badge_documentation| image:: https://readthedocs.org/projects/pylovo/badge/?version=latest
    :target: https://pylovo.readthedocs.io/en/main/?badge=main
    :alt: Documentation