Naming Convention for Network Objects (chr_name)
==================================================

General Description:
--------------------
Each element in the pandapower network has a unique structured name (chr_name),
composed of numeric segments that encode its hierarchical and topological position.
The name allows identification of the voltage level, network, busbar, branch,
connected main nodes, object type, and object number.

Example:
---------
chr_name = 7182182001001005005002006002

Segment Structure:
------------------
Position | Length | Segment Name           | Example | Meaning
---------------------------------------------------------------------
1         | 1       | Netzebene              | 7       | Voltage level (1 = HöS … 7 = NS)
2-7       | 6 (2×3) | Netznummer (1+2)       | 182     | Network identifier within voltage level
8–13      | 6 (2×3) | SS-Nummer (1+1)        | 182     | Busbar number
14–19     | 6 (2×3) | Strangnummer (1+2)     | 001001  | Branch number
20–25     | 6 (2×3) | Hauptknoten 1 + 2      | 002006  | Main nodes connected by the element
26–27     | 2       | Objekttyp              | 06      | Object type (see below)
28–30     | 3       | Objektnummer           | 002     | Running number within type

Object Type Codes:
------------------
1  = Knoten (node)
2  = US-SS (busbar)
3  = Verzweigung (branch/junction)
4  = Externes Netz (external grid)
5  = Trafo (transformer)
6  = Leitung (line/cable)
7  = Schalter (switch)
8  = Last (load)
9  = EZA (generator)
10 = Feld (field)
11 = Schalter intern (internal switch)

Naming Logic:
-------------
- Elements are named according to the two main nodes (Hauptknoten) they connect.
- Hauptknoten (HK) are:
  * Low-voltage side of a substation
  * Junction with more than two lines
  * End node of a branch (only one connection)
- Open switches: "Netznummer", "SS-Nummer", and "Strangnummer" appear twice.
- Closed switches: cannot connect two different networks/branches (they merge them).
- All other elements have the same three values for both ends.

Advantages:
-----------
+ Position and hierarchy can be derived from name
+ Enables systematic filtering and script access

Disadvantages:
--------------
- Must be renamed after topology changes (no permanent ID)
- Requires structured generation script
- Currently implemented for Netzebenen 4–7 (medium to low voltage)

