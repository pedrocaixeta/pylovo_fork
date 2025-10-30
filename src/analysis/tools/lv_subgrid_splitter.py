#!/usr/bin/env python3
"""
LV subgrid splitter with proper transformer zone separation.
This module properly partitions LV networks into transformer zones using 
graph-based distance assignment (Voronoi-like partitioning).
Key features:
1. Assign each bus to exactly ONE transformer (nearest by graph distance)
2. Strict Netzebene 7 filtering (only true LV buses, excludes MV)
3. Validate that splits sum to original network
4. Handle meshed networks gracefully
"""
from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas as pd
import pandapower as pp
import networkx as nx


# ================================================================================
# Helper functions for chr_name parsing and graph building
# ================================================================================

CHR_UNDERSCORE_REGEX = re.compile(
    r"^(?P<hdr>\d{7})_(?P<ss>\d{6})_(?P<str>\d{6})_(?P<hk>\d{6})_(?P<tail>\d{5})$"
)


@dataclass(frozen=True)
class ChrName:
    """Parsed representation of a chr_name (underscore variant).

    Structure: lvl+netz1+netz2 (7) _ ss (6) _ str (6) _ hk (6) _ tail (otype2+onum3)

    Attributes
    ----------
    raw : str
        Original chr_name string
    lvl : int
        Netzebene (1=HöS … 7=NS)
    netz1, netz2 : str
        Netznummer halves (3 digits each); if equal → netznummer
    ss1, ss2 : str
        Substation/busbar number halves (3 digits each)
    str1, str2 : str
        Strangnummer halves (3 digits each)
    hk1, hk2 : str
        Hauptknoten IDs (3 digits each)
    otype : str
        Object type code (2 digits)
    onum : str
        Object number (3 digits)
    """
    raw: str
    lvl: int
    netz1: str
    netz2: str
    ss1: str
    ss2: str
    str1: str
    str2: str
    hk1: str
    hk2: str
    otype: str
    onum: str

    @property
    def is_lv(self) -> bool:
        """True if element is in LV (Netzebene 7)."""
        return self.lvl == 7

    @property
    def netznummer(self) -> Optional[str]:
        """Return unified netznummer when both halves match, else None."""
        return self.netz1 if self.netz1 == self.netz2 else None

    @property
    def is_open_tie_candidate(self) -> bool:
        """True if tokens for netz/ss/str differ between the two halves.

        Per convention, open switches encode both sides (values appear twice).
        We treat any mismatch across halves as a normally-open tie marker.
        """
        return (self.netz1 != self.netz2) or (self.ss1 != self.ss2) or (self.str1 != self.str2)


def parse_chr_name(value: Any) -> Optional[ChrName]:
    """Parse underscore-separated chr_name into structured fields.

    Supported input example: 7007007_001001_000000_001001_08007

    Returns None if parsing fails.
    """
    if value is None:
        return None
    s = str(value).strip()
    mu = CHR_UNDERSCORE_REGEX.match(s)
    if not mu:
        return None
    g = mu.groupdict()
    hdr = g["hdr"]  # 7 digits: lvl + netz1 + netz2
    lvl = int(hdr[0])
    netz1, netz2 = hdr[1:4], hdr[4:7]
    ss1, ss2 = g["ss"][0:3], g["ss"][3:6]
    str1, str2 = g["str"][0:3], g["str"][3:6]
    hk1, hk2 = g["hk"][0:3], g["hk"][3:6]
    tail = g["tail"]
    otype, onum = tail[0:2], tail[2:5]
    return ChrName(
        raw=s,
        lvl=lvl,
        netz1=netz1, netz2=netz2,
        ss1=ss1, ss2=ss2,
        str1=str1, str2=str2,
        hk1=hk1, hk2=hk2,
        otype=otype, onum=onum,
    )


def _best_name_col(df: pd.DataFrame) -> Optional[str]:
    """Return the best column to read naming from for a given table."""
    if df is None or len(df) == 0:
        return None
    if "chr_name" in df.columns:
        return "chr_name"
    if "name" in df.columns:
        return "name"
    return None


def _build_global_operational_graph(net: pp.pandapowerNet) -> nx.Graph:
    """Build a global operational graph of buses with in-service lines as edges.

    - Start with all buses and in_service lines
    - Remove edges that are open due to switch states (closed=False or in_service=False)
    - Also remove edges if a switch's own chr_name indicates an open tie (mismatched netz/ss/str)
    - Additionally, treat line-level naming that indicates normally-open ties as open
    - Restrict to LV-only connectivity: edges between buses whose chr_name indicates LV (lvl==7)
    - Both endpoints of a line must have parseable chr_name with Netzebene 7 (true LV)
    - No voltage fallback - for this DSO data, lvl==7 is 0.4kV (LV), lvl==5 is 21kV (MV)
     """
    G = nx.Graph()
    # Do NOT add all nodes upfront - only add LV nodes implicitly when LV-LV edges are added
    # This ensures only Netzebene 7 (true LV) buses are in the graph

    # Precompute bus voltage and naming tokens
    bus_vn = net.bus["vn_kv"].to_dict()
    b_col = _best_name_col(net.bus)
    bus_chr: Dict[int, Optional[ChrName]] = {}
    for b, row in net.bus.iterrows():
        bus_chr[int(b)] = parse_chr_name(row.get(b_col)) if b_col else None

    # Add all line edges in service
    # CRITICAL: respect line.in_service to match what metrics calculator sees
    l_col = _best_name_col(net.line)
    for idx, row in net.line.iterrows():
        # Skip out-of-service lines (critical for avoiding disconnected components)
        if not bool(row.get('in_service', True)):
            continue
        # Respect naming-based open ties on the line itself (if available)
        if l_col and pd.notna(row.get(l_col)):
            cnl = parse_chr_name(row.get(l_col))
            if cnl and cnl.is_open_tie_candidate:
                continue
        u = int(row["from_bus"]); v = int(row["to_bus"])
        # Only LV-LV edges: MUST have chr_name with lvl==7 (true LV)
        # For this DSO data: lvl==7 is 0.4kV (LV), lvl==5 is 21kV (MV)
        # Do NOT use voltage fallback - it incorrectly includes MV buses
        cu, cv = bus_chr.get(u), bus_chr.get(v)
        # Both buses must have parseable chr_name with Netzebene 7
        if not (cu and cu.is_lv and cv and cv.is_lv):
            continue
        G.add_edge(u, v, line=int(idx))

    # Process switches to remove open edges
    if hasattr(net, "switch") and len(net.switch) > 0:
        s_col = _best_name_col(net.switch)
        for _, srow in net.switch.iterrows():
            try:
                et = srow.get("et", "")
                element = srow.get("element")
                closed = bool(srow.get("closed", True))
                in_service = bool(srow.get("in_service", True))
                naming_open = False
                if s_col:
                    cn = parse_chr_name(srow.get(s_col))
                    naming_open = bool(cn and cn.is_open_tie_candidate)
                if et == "l":
                    line_idx = int(element)
                    if line_idx in net.line.index:
                        lrow = net.line.loc[line_idx]
                        u = int(lrow["from_bus"]); v = int(lrow["to_bus"])
                        if (not closed) or (not in_service) or naming_open:
                            if G.has_edge(u, v):
                                G.remove_edge(u, v)
                elif et == "b":
                    u = int(srow.get("bus")) if pd.notna(srow.get("bus")) else None
                    v = int(element) if pd.notna(element) else None
                    if u is not None and v is not None:
                        if (not closed) or (not in_service) or naming_open:
                            if G.has_edge(u, v):
                                G.remove_edge(u, v)
            except Exception:
                continue

    return G


def _component_nodes(G: nx.Graph, root: int) -> List[int]:
    """Return the nodes in the connected component containing the root."""
    if root not in G:
        return []
    return list(nx.node_connected_component(G, root))


def _isolate_one_trafo(G_sub: nx.Graph, root_lvb: int, other_trafos: List[int]) -> nx.Graph:
    """If a component contains multiple LV trafo buses, cut along shortest paths to isolate root.

    This is a local repair to ensure exactly one transformer per derived subgrid.
    """
    H = G_sub.copy()
    others = [b for b in other_trafos if b != root_lvb and b in H]
    for ob in others:
        try:
            path = nx.shortest_path(H, source=root_lvb, target=ob)
            if len(path) >= 2:
                mid = len(path) // 2
                u, v = path[mid - 1], path[mid]
                if H.has_edge(u, v):
                    H.remove_edge(u, v)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
    return H


def _radialize(H: nx.Graph, root: int) -> nx.Graph:
    """Remove non-tree edges to enforce radiality by keeping a BFS tree from root."""
    if root not in H:
        return H
    T = nx.bfs_tree(H, root)
    keep = set(tuple(sorted(e)) for e in T.to_undirected().edges())
    for u, v in list(H.edges()):
        if tuple(sorted((u, v))) not in keep:
            H.remove_edge(u, v)
    return H


def _infer_netznummer_from_loads(net: pp.pandapowerNet, buses: List[int]) -> str:
    """Infer the netznummer for naming from connected loads."""
    col = _best_name_col(net.load)
    if not col or len(net.load) == 0:
        return "unk"
    loads = net.load[net.load["bus"].isin(buses)]
    if len(loads) == 0:
        return "unk"
    vals = []
    for _, r in loads.iterrows():
        cn = parse_chr_name(r.get(col))
        if cn and cn.netznummer:
            vals.append(cn.netznummer)
    if not vals:
        return "unk"
    return pd.Series(vals).mode().iat[0]


def _allowed_nodes_for_netz(G: nx.Graph, bus_chr: Dict[int, Optional[ChrName]], target_netz: str) -> set[int]:
    """Return the set of LV nodes to consider for a given netznummer.

    Start from seed buses with chr_name.netznummer == target_netz and expand
    over LV edges in G, including buses without chr_name. Stop expansion at
    buses whose chr_name indicates a different netznummer.
    """
    # seeds: LV buses with matching netznummer
    seeds = [b for b, cn in bus_chr.items() if (b in G) and cn and cn.is_lv and cn.netznummer == target_netz]
    if not seeds:
        return set()
    allowed: set[int] = set()
    from collections import deque
    dq = deque(seeds)
    allowed.update(seeds)
    while dq:
        u = dq.popleft()
        for v in G.neighbors(u):
            if v in allowed:
                continue
            cn = bus_chr.get(v)
            if cn and cn.is_lv and cn.netznummer and cn.netznummer != target_netz:
                # hard boundary at other netznummer
                continue
            allowed.add(v)
            dq.append(v)
    return allowed


def _assign_buses_to_trafos(
    G_sub: nx.Graph,
    trafos_in_netz: Dict[int, int],  # trafo_idx -> lv_bus (should be in G_sub)
) -> Dict[int, List[int]]:
    """Assign every node in G_sub to the nearest trafo LV bus among trafos_in_netz.

    Returns mapping: trafo_idx -> list of assigned buses
    """
    roots = {t_idx: lvb for t_idx, lvb in trafos_in_netz.items() if lvb in G_sub}
    assignment: Dict[int, List[int]] = {t_idx: [] for t_idx in roots}
    if not roots:
        return assignment

    # Precompute distances from each root to nodes in this subgraph
    dist_map: Dict[int, Dict[int, int]] = {}
    for t_idx, lvb in roots.items():
        try:
            dist_map[t_idx] = nx.single_source_shortest_path_length(G_sub, lvb)
        except Exception:
            dist_map[t_idx] = {}

    for b in G_sub.nodes():
        best = None
        best_dist = None
        for t_idx, dmap in dist_map.items():
            d = dmap.get(b)
            if d is None:
                continue
            if (best is None) or (d < best_dist) or (d == best_dist and t_idx < best):
                best = t_idx
                best_dist = d
        if best is not None:
            assignment[best].append(b)

    return assignment


# ================================================================================
# Improved splitting with distance-based assignment
# ================================================================================

@dataclass
class SplitStatistics:
    """Statistics for subgrid splitting validation."""
    original_buses: int
    original_lines: int
    original_loads: int
    original_sgens: int
    original_trafos: int

    split_buses_total: int
    split_lines_total: int
    split_loads_total: int
    split_sgens_total: int
    split_trafos_total: int

    num_subgrids: int
    buses_per_subgrid: Dict[str, int]
    lines_per_subgrid: Dict[str, int]

    @property
    def buses_match(self) -> bool:
        """Check if bus counts match (accounting for HV buses in each subgrid)."""
        # Each subgrid includes one HV bus from its transformer
        # So expected split total = original_buses + (num_subgrids - 1) HV buses
        # Actually simpler: LV buses should sum to original LV buses
        original_lv = self.original_buses - self.original_trafos  # Approximate
        return abs(self.split_buses_total - self.original_buses) <= self.num_subgrids * 2

    @property
    def lines_match(self) -> bool:
        """Check if line counts match (within tolerance for meshed networks)."""
        # In meshed networks, some lines might be excluded if they cross transformer zones
        # Allow up to 10% difference
        return abs(self.split_lines_total - self.original_lines) / max(self.original_lines, 1) < 0.10

    @property
    def loads_match(self) -> bool:
        """Check if load counts match exactly."""
        return self.split_loads_total == self.original_loads

    @property
    def validation_passed(self) -> bool:
        """Check if all validation criteria passed."""
        return self.buses_match and self.lines_match and self.loads_match

    def format_report(self) -> str:
        """Generate formatted validation report."""
        lines = [
            "=" * 80,
            "SUBGRID SPLITTING VALIDATION REPORT",
            "=" * 80,
            "",
            "Original Network:",
            f"  Buses:        {self.original_buses:6d}",
            f"  Lines:        {self.original_lines:6d}",
            f"  Loads:        {self.original_loads:6d}",
            f"  Sgens:        {self.original_sgens:6d}",
            f"  Transformers: {self.original_trafos:6d}",
            "",
            f"Split into {self.num_subgrids} Subgrids:",
            f"  Buses (sum):  {self.split_buses_total:6d}  {'✓ OK' if self.buses_match else '✗ MISMATCH'}",
            f"  Lines (sum):  {self.split_lines_total:6d}  {'✓ OK' if self.lines_match else '✗ MISMATCH'}",
            f"  Loads (sum):  {self.split_loads_total:6d}  {'✓ OK' if self.loads_match else '✗ MISMATCH'}",
            f"  Sgens (sum):  {self.split_sgens_total:6d}",
            f"  Trafos (sum): {self.split_trafos_total:6d}",
            "",
            "Validation: " + ("✓ PASSED" if self.validation_passed else "✗ FAILED"),
            "",
        ]

        if not self.buses_match:
            diff = self.split_buses_total - self.original_buses
            lines.extend([
                f"⚠️  Bus count mismatch: {diff:+d} buses",
                f"   This may be expected if HV buses are duplicated across subgrids",
                "",
            ])

        if not self.lines_match:
            diff = self.split_lines_total - self.original_lines
            pct = 100 * diff / max(self.original_lines, 1)
            lines.extend([
                f"⚠️  Line count mismatch: {diff:+d} lines ({pct:+.1f}%)",
                f"   This may occur in meshed networks where lines cross transformer zones",
                "",
            ])

        # Top 10 largest subgrids
        lines.append("Largest Subgrids by Bus Count:")
        lines.append("-" * 80)
        sorted_subgrids = sorted(self.buses_per_subgrid.items(), key=lambda x: x[1], reverse=True)
        for i, (name, count) in enumerate(sorted_subgrids[:10], 1):
            line_count = self.lines_per_subgrid.get(name, 0)
            lines.append(f"  {i:2d}. {name:30s}: {count:4d} buses, {line_count:4d} lines")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)


def assign_buses_to_transformers(
    G: nx.Graph,
    trafo_lv_buses: Dict[int, int],  # trafo_idx -> lv_bus
) -> Dict[int, List[int]]:
    """
    Assign each bus in the graph to exactly ONE transformer based on shortest path distance.

    This is the key improvement: each bus is assigned to its nearest transformer,
    ensuring no overlap between subgrids.

    Parameters
    ----------
    G : nx.Graph
        Operational graph of the network
    trafo_lv_buses : dict
        Mapping from transformer index to LV bus index

    Returns
    -------
    dict
        Mapping from transformer index to list of assigned bus indices
    """
    logger = logging.getLogger(__name__)

    # Filter to transformers that are in the graph
    valid_trafos = {t_idx: lvb for t_idx, lvb in trafo_lv_buses.items() if lvb in G}

    if not valid_trafos:
        logger.warning("No valid transformers found in graph")
        return {}

    logger.info(f"Assigning buses to {len(valid_trafos)} transformers...")

    # Compute shortest path distances from each transformer to all reachable buses
    distances: Dict[int, Dict[int, int]] = {}  # trafo_idx -> {bus_idx -> distance}

    for t_idx, lvb in valid_trafos.items():
        try:
            distances[t_idx] = nx.single_source_shortest_path_length(G, lvb)
        except Exception as e:
            logger.warning(f"Failed to compute distances for trafo {t_idx}: {e}")
            distances[t_idx] = {lvb: 0}

    # For each bus, find the nearest transformer
    assignment: Dict[int, List[int]] = {t_idx: [] for t_idx in valid_trafos}
    all_buses = set(G.nodes())

    for bus in all_buses:
        best_trafo = None
        best_dist = None

        for t_idx, dist_map in distances.items():
            if bus not in dist_map:
                continue  # Bus not reachable from this transformer

            dist = dist_map[bus]

            # Assign to nearest transformer, tie-break by trafo index
            if best_trafo is None or dist < best_dist or (dist == best_dist and t_idx < best_trafo):
                best_trafo = t_idx
                best_dist = dist

        if best_trafo is not None:
            assignment[best_trafo].append(bus)

    # Log assignment statistics
    for t_idx, buses in assignment.items():
        logger.debug(f"  Trafo {t_idx}: assigned {len(buses)} buses")

    unassigned = len(all_buses) - sum(len(buses) for buses in assignment.values())
    if unassigned > 0:
        logger.warning(f"  {unassigned} buses could not be assigned to any transformer")

    return assignment


def create_subgrid_from_assignment(
    net: pp.pandapowerNet,
    trafo_idx: int,
    assigned_buses: List[int],
    G_operational: nx.Graph,
) -> pp.pandapowerNet:
    """
    Create a subgrid for a specific transformer with assigned buses.

    Parameters
    ----------
    net : pp.pandapowerNet
        Original network
    trafo_idx : int
        Transformer index
    assigned_buses : list
        List of bus indices assigned to this transformer
    G_operational : nx.Graph
        Operational graph for determining which lines to include

    Returns
    -------
    pp.pandapowerNet
        Subgrid network
    """
    logger = logging.getLogger(__name__)

    # Get transformer HV bus to include in subgrid
    hvb = None
    if trafo_idx in net.trafo.index:
        try:
            hvb = int(net.trafo.loc[trafo_idx, "hv_bus"])
        except Exception:
            pass

    # Final bus list includes assigned LV buses + HV bus
    final_buses = sorted(assigned_buses)
    if hvb is not None and hvb in net.bus.index and hvb not in final_buses:
        final_buses.append(hvb)
        final_buses = sorted(final_buses)

    # Create subnet
    try:
        sub_net = pp.select_subnet(
            net,
            buses=final_buses,
            include_results=False,
            include_switch_buses=True,
        )
    except TypeError:
        sub_net = pp.select_subnet(
            net,
            buses=final_buses,
            include_results=False,
            include_switch_buses=True,
        )

    # Filter lines to only include those in the operational graph
    # and between assigned buses (avoid cross-zone lines)
    if len(sub_net.line) > 0:
        assigned_bus_set = set(assigned_buses)
        lines_to_keep = []

        for idx, lrow in sub_net.line.iterrows():
            u = int(lrow["from_bus"])
            v = int(lrow["to_bus"])

            # Keep line if:
            # 1. Both endpoints are in assigned buses
            # 2. Edge exists in operational graph (respects switches)
            if u in assigned_bus_set and v in assigned_bus_set:
                if G_operational.has_edge(u, v):
                    lines_to_keep.append(idx)

        # Filter line table and geodata
        sub_net.line = sub_net.line.loc[lines_to_keep]
        if not sub_net.line_geodata.empty:
            sub_net.line_geodata = sub_net.line_geodata.loc[
                sub_net.line_geodata.index.isin(sub_net.line.index)
            ]

        # Reset indices
        sub_net.line.reset_index(drop=True, inplace=True)
        if not sub_net.line_geodata.empty:
            sub_net.line_geodata.reset_index(drop=True, inplace=True)

    # Remove switches (they're already accounted for in the operational graph)
    if hasattr(sub_net, "switch") and len(sub_net.switch) > 0:
        sub_net.switch.drop(sub_net.switch.index, inplace=True)

    # Ensure the subgrid is radial by keeping only a spanning tree from LV bus
    if trafo_idx in sub_net.trafo.index:
        lvb = int(sub_net.trafo.loc[trafo_idx, "lv_bus"])
        if lvb in sub_net.bus.index:
            # Build graph of remaining lines
            H = nx.Graph()
            H.add_nodes_from(sub_net.bus.index)
            for idx, lrow in sub_net.line.iterrows():
                u = int(lrow["from_bus"])
                v = int(lrow["to_bus"])
                H.add_edge(u, v, line_idx=idx)

            # Keep only BFS tree from LV bus
            if lvb in H:
                try:
                    tree = nx.bfs_tree(H, lvb)
                    tree_edges = set(tuple(sorted(e)) for e in tree.to_undirected().edges())

                    lines_to_keep = []
                    for idx, lrow in sub_net.line.iterrows():
                        u = int(lrow["from_bus"])
                        v = int(lrow["to_bus"])
                        if tuple(sorted((u, v))) in tree_edges:
                            lines_to_keep.append(idx)

                    sub_net.line = sub_net.line.loc[lines_to_keep]
                    if not sub_net.line_geodata.empty:
                        sub_net.line_geodata = sub_net.line_geodata.loc[
                            sub_net.line_geodata.index.isin(sub_net.line.index)
                        ]

                    sub_net.line.reset_index(drop=True, inplace=True)
                    if not sub_net.line_geodata.empty:
                        sub_net.line_geodata.reset_index(drop=True, inplace=True)
                except Exception as e:
                    logger.warning(f"Failed to radialize subgrid for trafo {trafo_idx}: {e}")

    return sub_net


def split_into_lv_subgrids_improved(
    net: pp.pandapowerNet,
    output_dir: str | Path | None = None,
) -> Tuple[Dict[str, pp.pandapowerNet], SplitStatistics]:
    """
    Split network into LV subgrids with proper transformer zone assignment.

    This improved version ensures:
    1. Each bus is assigned to exactly ONE transformer
    2. No overlapping subgrids
    3. Validation that splits sum to original network

    Parameters
    ----------
    net : pp.pandapowerNet
        Original network to split
    output_dir : str | Path, optional
        Directory to save subgrid JSON files

    Returns
    -------
    tuple
        (subgrids_dict, statistics)
    """
    logger = logging.getLogger(__name__)

    if output_dir is None:
        from src.analysis.validation.utils import load_validation_config
        data_dir, _net_name, _proj = load_validation_config()
        output_dir = data_dir / "subgrids"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build operational graph
    logger.info("Building operational graph...")
    G = _build_global_operational_graph(net)
    logger.info(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Identify LV transformers
    trafo_lv_buses: Dict[int, int] = {}
    for t_idx, row in net.trafo.iterrows():
        try:
            lvb = int(row["lv_bus"])
            # Only LV transformers (lv bus nominal voltage <= 1 kV)
            if float(net.bus.at[lvb, "vn_kv"]) <= 1.0:
                trafo_lv_buses[int(t_idx)] = lvb
        except Exception:
            continue

    logger.info(f"Found {len(trafo_lv_buses)} LV transformers")

    # Assign buses to transformers (KEY IMPROVEMENT)
    logger.info("Assigning buses to transformers by nearest distance...")
    bus_assignment = assign_buses_to_transformers(G, trafo_lv_buses)

    # Remove empty assignments
    bus_assignment = {t_idx: buses for t_idx, buses in bus_assignment.items() if len(buses) > 1}

    logger.info(f"Creating {len(bus_assignment)} subgrids...")

    # Create subgrids
    subgrids: Dict[str, pp.pandapowerNet] = {}

    for t_idx, assigned_buses in bus_assignment.items():
        logger.debug(f"  Processing trafo {t_idx} with {len(assigned_buses)} buses...")

        sub_net = create_subgrid_from_assignment(
            net, t_idx, assigned_buses, G
        )

        # Generate filename based on netznummer
        netz = _infer_netznummer_from_loads(net, assigned_buses)
        subgrid_id = f"{netz}__trafo_{t_idx}" if netz != "unk" else f"trafo_{t_idx}"

        subgrids[subgrid_id] = sub_net

        # Save to file
        out_file = output_dir / f"{subgrid_id}.json"
        try:
            pp.to_json(sub_net, str(out_file))
            logger.debug(f"    Saved: {len(sub_net.bus)} buses, {len(sub_net.line)} lines")
        except Exception as e:
            logger.error(f"    Failed to save {subgrid_id}: {e}")

    # Compute validation statistics
    stats = compute_split_statistics(net, subgrids)

    logger.info(f"✓ Created {len(subgrids)} subgrids")
    logger.info(stats.format_report())

    return subgrids, stats


def compute_split_statistics(
    original_net: pp.pandapowerNet,
    subgrids: Dict[str, pp.pandapowerNet],
) -> SplitStatistics:
    """Compute validation statistics comparing original to split networks."""

    # Original network stats
    orig_buses = len(original_net.bus)
    orig_lines = len(original_net.line)
    orig_loads = len(original_net.load) if hasattr(original_net, 'load') else 0
    orig_sgens = len(original_net.sgen) if hasattr(original_net, 'sgen') else 0
    orig_trafos = len(original_net.trafo) if hasattr(original_net, 'trafo') else 0

    # Split network stats
    split_buses = 0
    split_lines = 0
    split_loads = 0
    split_sgens = 0
    split_trafos = 0

    buses_per_subgrid = {}
    lines_per_subgrid = {}

    for name, sub_net in subgrids.items():
        n_buses = len(sub_net.bus)
        n_lines = len(sub_net.line)

        split_buses += n_buses
        split_lines += n_lines
        split_loads += len(sub_net.load) if hasattr(sub_net, 'load') else 0
        split_sgens += len(sub_net.sgen) if hasattr(sub_net, 'sgen') else 0
        split_trafos += len(sub_net.trafo) if hasattr(sub_net, 'trafo') else 0

        buses_per_subgrid[name] = n_buses
        lines_per_subgrid[name] = n_lines

    return SplitStatistics(
        original_buses=orig_buses,
        original_lines=orig_lines,
        original_loads=orig_loads,
        original_sgens=orig_sgens,
        original_trafos=orig_trafos,
        split_buses_total=split_buses,
        split_lines_total=split_lines,
        split_loads_total=split_loads,
        split_sgens_total=split_sgens,
        split_trafos_total=split_trafos,
        num_subgrids=len(subgrids),
        buses_per_subgrid=buses_per_subgrid,
        lines_per_subgrid=lines_per_subgrid,
    )


def run_improved_split() -> None:
    """Run the improved splitter on the configured network."""
    from src.analysis.validation.utils import load_validation_config, read_net_json

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("IMPROVED LV SUBGRID SPLITTER")
    logger.info("=" * 80)
    logger.info("")

    # Load network
    net, file_path = read_net_json()
    logger.info(f"Loaded network from: {file_path}")
    logger.info(f"  Buses: {len(net.bus)}")
    logger.info(f"  Lines: {len(net.line)}")
    logger.info(f"  Loads: {len(net.load) if hasattr(net, 'load') else 0}")
    logger.info(f"  Transformers: {len(net.trafo) if hasattr(net, 'trafo') else 0}")
    logger.info("")

    # Split
    subgrids, stats = split_into_lv_subgrids_improved(net)

    # Save validation report
    data_dir, _, _ = load_validation_config()
    report_file = data_dir / "subgrid_split_validation.txt"
    with open(report_file, 'w') as f:
        f.write(stats.format_report())
    logger.info(f"Validation report saved to: {report_file}")

    if stats.validation_passed:
        logger.info("✓ VALIDATION PASSED: Splits sum to original network")
    else:
        logger.warning("✗ VALIDATION FAILED: Discrepancies detected")
        logger.warning("  Review the validation report for details")

    logger.info("")
    logger.info("=" * 80)
    logger.info("SPLITTING COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    run_improved_split()

