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

**Quick Start**
------------

0. **Requirements**: Python 3.12+ and PostgreSQL with PostGIS extension
1. **Setup InfDB**: Clone and set up the `InfDB <https://github.com/tum-ens/InfDB>`_ system using Docker
2. **Run preprocessing pipeline**: Execute the data preprocessing as described in the InfDB documentation to populate InfDB with harmonized datasets
3. **Clone pylovo**: ``git clone https://github.com/tum-ens/pylovo.git``
4. **Install dependencies**: ``uv sync`` (see `documentation <https://pylovo.readthedocs.io/en/main/installation.html>`_ for more options)
5. **Configure connection**: Set up ``config_database.yaml`` and ``.env`` file to connect to the previously created InfDB instance
6. **Build pylovo database**: Run ``main_constructor.py`` to set up the pylovo database
7. **Generate grids**: Configure ``config_generation.yaml`` and run ``main_generation.py`` to create synthetic LV grids
8. **Analyze results**: Use provided visualization tools and statistical analysis features

This setup ensures access to the full preprocessing pipeline with 3D building models, census data, and cadastral information for enhanced accuracy in grid generation.
For detailed tutorials and documentation, see the `notebook_tutorials` directory and visit `https://pylovo.readthedocs.io <https://pylovo.readthedocs.io>`_.

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