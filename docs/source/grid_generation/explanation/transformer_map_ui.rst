Transformer Map UI
==================

The Transformer Map UI is an interactive web-based tool for visualizing, managing, and editing transformer positions before generating grids.
It provides a user-friendly interface for working with transformer data imported from OpenStreetMap and allows manual addition, editing, and deletion of transformer positions.

Overview
--------

The Transformer Map UI is designed to:

* Visualize existing transformer positions on an interactive map
* Allow manual addition of new transformer positions
* Edit transformer capacities and properties
* Delete unwanted transformer positions
* Work with specific postal code (PLZ) areas
* Provide real-time feedback and validation

Features
--------

Interactive Map
~~~~~~~~~~~~~~~

* **Leaflet-based mapping**: Uses OpenStreetMap tiles for accurate geographical representation
* **Zoom and pan**: Navigate to specific areas of interest
* **Auto-fit bounds**: Automatically zooms to the selected PLZ area
* **Performance optimized**: Efficient rendering for large datasets

Transformer Management
~~~~~~~~~~~~~~~~~~~~~~

* **Visual distinction**: 
  - Blue markers: OSM-imported transformers
  - Red markers: Manually added transformers
* **Interactive markers**: Click to view transformer details
* **Capacity management**: Select from predefined transformer capacities
* **Real-time updates**: Changes appear immediately on the map

User Interface
~~~~~~~~~~~~~~

* **PLZ selection**: Input field for postal code selection
* **Current PLZ display**: Shows the currently loaded area
* **Capacity dropdown**: Select transformer capacity from configuration
* **Control buttons**: Load data, clear map, add transformers
* **Status indicators**: Real-time feedback on operations
* **Legend**: Visual guide for marker types

Usage
-----

Starting the UI
~~~~~~~~~~~~~~~

The Transformer Map UI can be launched using the dedicated import script:

.. code-block:: bash

    uv run python runme/import/import_transformers_via_ui.py --port 8080

Optional parameters:
* ``--host``: Host address (default: 0.0.0.0)
* ``--port``: Port number (default: 8080)

Access the interface by opening your web browser and navigating to:
``http://localhost:8080``

Basic Workflow
~~~~~~~~~~~~~~

1. **Load Data**:
   - Enter a German postal code (PLZ) in the input field
   - Click "Load Data" to fetch transformer positions for that area
   - The map will automatically zoom to the PLZ area
   - Existing transformers will appear as blue markers

2. **Add Transformers**:
   - Select a transformer capacity from the dropdown menu
   - Click "Start Adding Transformers"
   - Click anywhere on the map to add a new transformer
   - New transformers appear as red markers immediately
   - The adding mode remains active until manually stopped

3. **Edit Transformers**:
   - Click on any existing transformer marker
   - A popup will show current transformer details
   - Use the capacity dropdown to change transformer capacity
   - Changes are saved automatically

4. **Delete Transformers**:
   - Click on a transformer marker to select it
   - Use the delete option in the popup
   - The transformer will be removed from the map and database

5. **Clear Map**:
   - Click "Clear Map" to remove all markers and reset the interface
   - This also clears the current PLZ selection

Technical Details
-----------------

Database Integration
~~~~~~~~~~~~~~~~~~~~

The UI integrates with the pylovo database through:

* **PreprocessingMixin**: Handles transformer data queries
* **DatabaseClient**: Manages database connections
* **PostGIS support**: Spatial queries for geographical data
* **Transaction management**: Ensures data consistency

API Endpoints
~~~~~~~~~~~~~

The UI provides several REST API endpoints:

* ``/api/plz-list``: Get available postal codes
* ``/api/plz-bounds/<plz>``: Get geographical bounds for a PLZ
* ``/api/transformer-positions/<plz>``: Get transformer positions for a PLZ
* ``/api/transformer-capacities``: Get available transformer capacities
* ``/api/add-transformer``: Add a new transformer
* ``/api/update-transformer-capacity``: Update transformer capacity
* ``/api/delete-transformer``: Delete a transformer

Data Formats
~~~~~~~~~~~~

* **WKT (Well-Known Text)**: Used for geographical data representation
* **EPSG:4326**: Standard GPS coordinate system for map display
* **EPSG:3035**: European Terrestrial Reference System for calculations
* **JSON**: API communication format

OSM ID Generation
~~~~~~~~~~~~~~~~

The UI uses a specific format for identifying transformers:

* **OSM-imported transformers**: Use their original OpenStreetMap ID (e.g., `123456789`)
* **Manually added transformers**: Use the format `manual/<timestamp>` (e.g., `manual/1694271234`)

The timestamp is generated using `int(time.time())` which provides:
* **Uniqueness**: Unix timestamp ensures unique IDs
* **Chronological ordering**: Newer transformers have higher IDs
* **Consistency**: Matches the existing pylovo notation convention

This format allows the system to distinguish between:
* Original OSM data (numeric IDs)
* User-added data (prefixed with `manual/`)

Configuration
~~~~~~~~~~~~~

Transformer capacities are loaded from ``config/config_generation.yaml``:

.. code-block:: yaml

    transformer_rated_power:
      - 100
      - 160
      - 250
      - 400
      - 630
      - 1000

Troubleshooting
---------------

Common Issues
~~~~~~~~~~~~~

1. **"Please load a PLZ first" error**:
   - Ensure you have loaded a PLZ area before trying to add transformers
   - Check that the PLZ input field is not empty

2. **Transformers not displaying**:
   - Verify the database connection is working
   - Check that transformer data exists for the selected PLZ
   - Ensure the database contains the required tables

3. **Map not loading**:
   - Check your internet connection for OpenStreetMap tiles
   - Verify the server is running on the correct port
   - Clear browser cache if needed

4. **Database connection errors**:
   - Ensure PostgreSQL is running
   - Verify database credentials in ``.env`` file
   - Check that the pylovo schema exists

Performance Considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Query limits**: Transformer queries are limited to 1000 results for performance
* **Caching**: Browser caching is disabled for development
* **Connection management**: Database connections are properly managed and closed
* **Memory usage**: Large datasets are handled efficiently

Browser Compatibility
~~~~~~~~~~~~~~~~~~~~~

The UI is compatible with modern web browsers that support:
* ES6 JavaScript features
* Fetch API
* Leaflet mapping library
* CSS Grid and Flexbox

Recommended browsers:
* Chrome 60+
* Firefox 55+
* Safari 12+
* Edge 79+

Development
-----------

File Structure
~~~~~~~~~~~~~~

The Transformer Map UI consists of:

* ``src/data_import/transformers_ui.py``: Main UI implementation
* ``runme/import/import_transformers_via_ui.py``: Launch script
* ``src/database/preprocessing_mixin.py``: Database operations
* ``config/config_generation.yaml``: Configuration

Key Components
~~~~~~~~~~~~~~

* **TransformerMapUI**: Main Flask application class
* **HTML Template**: Embedded HTML with JavaScript
* **CSS Styling**: Responsive design with modern UI elements
* **JavaScript Functions**: Client-side functionality
* **Database Mixins**: Server-side data operations

Extending the UI
~~~~~~~~~~~~~~~~

The UI can be extended by:

* Adding new API endpoints in the Flask routes
* Modifying the HTML template for new UI elements
* Adding new JavaScript functions for client-side functionality
* Extending database operations in the mixins
* Adding new configuration options

Security Considerations
~~~~~~~~~~~~~~~~~~~~~~~

* **Input validation**: All user inputs are validated
* **SQL injection prevention**: Parameterized queries are used
* **CORS handling**: Proper cross-origin resource sharing
* **Error handling**: Graceful error handling and user feedback

For more information about the underlying database structure and data import processes, see :doc:`database` and :doc:`building_data_import`.
