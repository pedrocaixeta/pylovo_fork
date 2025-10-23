# SWD Naming Convention for Network Objects (chr_name)

## Overview

SWD networks use a hierarchical naming convention where each element has a structured `chr_name` that encodes its position in the network hierarchy. Unlike Forchheim's continuous 30-digit format, SWD uses underscore-separated segments.

## Structure

```
Example: 7137137_001001_005005_002006_06_002
         ^^^^^^^_^^^^^^^_^^^^^^^_^^^^^^^_^^_^^^
         |       |       |       |       |  |
         |       |       |       |       |  └─ Object number (3 digits)
         |       |       |       |       └──── Object type (2 digits)
         |       |       |       └──────────── Further connections (6 digits)
         |       |       └──────────────────── Optional repetition (6 digits)
         |       └──────────────────────────── Main nodes 1+2 (6 digits)
         └──────────────────────────────────── Grid identifier (7 digits)
```

### Grid Identifier (7 digits)
The first part before the underscore identifies the grid:

- **Position 1**: Netzebene (voltage level)
  - 1 = HöS (highest voltage)
  - ...
  - 7 = NS (low voltage / LV)

- **Position 2-3**: Netznummer (network identifier)
- **Position 4-5**: SS-Nummer (substation number)
- **Position 6-7**: Strangnummer (branch number)

### Main Nodes (6 digits = 2×3)
Positions 8-13: Two 3-digit node identifiers that the element connects

### Optional Fields
- **Positions 14-19**: Optional repetition (for complex connections)
- **Positions 20-25**: Further connections (used for switches connecting different branches)

### Object Type (2 digits)
Position 26-27:
- `01` = Knoten (node)
- `02` = US-SS (substation)
- `03` = Verzweigung (branch/junction)
- `04` = Externes Netz (external grid)
- `05` = Trafo (transformer)
- `06` = Leitung (line/cable)
- `07` = Schalter (switch)
- `08` = Last (load)
- `09` = EZA (generator)
- `10` = Feld (field)
- `11` = Schalter intern (internal switch)

### Object Number (3 digits)
Position 28-30: Running number within the object type

## Examples

### LV Bus
```
chr_name: 7137137_001001_005005_002006_01_001
          ^^^^^^^                         ^^
          Grid 7137137                    Node type
          (LV network, net 13, substation 71, branch 37)
```

### Line/Cable
```
chr_name: 7137137_001002_005005_002006_06_042
          ^^^^^^^                         ^^_^^^
          Same grid                       Line #42
```

### Load
```
chr_name: 7137137_001001_005005_002006_08_015
          ^^^^^^^                         ^^_^^^
          Same grid                       Load #15
```

## Differences from Forchheim

| Feature | SWD | Forchheim |
|---------|-----|-----------|
| Format | Underscore-separated | Continuous digits |
| Length | Variable (~30 chars) | Fixed 30 digits |
| Grid ID | First 7 digits before '_' | Positions 1-7 |
| Parsing | Split by '_' | Fixed positions |

## Grid Splitting

For splitting multi-grid networks, use the **grid identifier** (first 7 digits):
- Extract everything before first underscore
- Group buses/lines/loads by this identifier
- Each unique identifier = one physical grid

## Parsing in Code

```python
from src.analysis.validation.naming_conventions import parse_swd_chr_name

chr_name = "7137137_001001_005005_002006_06_042"
parsed = parse_swd_chr_name(chr_name)

# Result:
# {
#   'netzebene': '7',
#   'netznummer': '13',
#   'ss_nummer': '71',
#   'strangnummer': '37',
#   'hauptknoten_1': '001',
#   'hauptknoten_2': '001',
#   'objekttyp': '06',
#   'objektnummer': '042',
#   'grid_id': '7137137'
# }
```

## Validation

The naming convention ensures:
- Unique identification of each element
- Hierarchical relationships are encoded
- Topology can be reconstructed from names

## Limitations

- Names must be updated after topology changes
- No permanent ID across topology modifications
- Requires consistent naming during grid generation

