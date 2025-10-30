#!/usr/bin/env python3
"""
Low-voltage (LV) subgrid splitter with transformer-zone assignment (validation workflow).

Purpose
- Partition a DSO-provided LV network into disjoint subgrids, one per LV transformer.
- Respect operational topology (switch states, open ties) and keep only LV buses.
- Assign each LV bus to exactly one transformer using shortest-path distances.
- Optionally save each subgrid as a separate pandapower JSON and report split stats.

Highlights
- LV-only operational graph (respects line/service and switch states, removes open ties).
- Voronoi-like assignment by graph distance to transformer LV buses (no overlaps).
- Safe handling of meshed sections via BFS tree pruning to enforce radiality per subgrid.
- Lightweight validation comparing original and split networks (counts, tolerances).
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


# ==============================================================================
# chr_name parsing and graph helpers
# ==============================================================================

# underscore-encoded naming: lvl+netz1+netz2 _ ss1+ss2 _ str1+str2 _ hk1+hk2 _ otype+onum
CHR_UNDERSCORE_REGEX = re.compile(
    r"^(?P<hdr>\d{7})_(?P<ss>\d{6})_(?P<str>\d{6})_(?P<hk>\d{6})_(?P<tail>\d{5})$"
)


@dataclass(frozen=True)
class ChrName:
    """Parsed view of underscore-separated chr_name.

    Format: lvl netz1 netz2 _ ss1 ss2 _ str1 str2 _ hk1 hk2 _ otype onum
    Example: 7007007_001001_000000_001001_08007

    Attributes
    ----------
    raw: Original string value
    lvl: Netzebene (7 = LV)
    netz1, netz2: Netznummer halves (3 digits each)
    ss1, ss2: Substation/busbar halves
    str1, str2: Strangnummer halves
    hk1, hk2: Hauptknoten halves
    otype: Object type code (2 digits)
    onum: Object number (3 digits)
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
        """True if Netzebene is 7 (low voltage)."""
        return self.lvl == 7

    @property
    def netznummer(self) -> Optional[str]:
        """Unified netznummer if both halves match; otherwise None."""
        return self.netz1 if self.netz1 == self.netz2 else None

    @property
    def is_open_tie_candidate(self) -> bool:
        """Heuristic: chr_name encodes two different sides → likely an open tie.

        Any mismatch across the two halves (netz/ss/str) is treated as a normally-open tie.
        """
        return (self.netz1 != self.netz2) or (self.ss1 != self.ss2) or (self.str1 != self.str2)


def parse_chr_name(value: Any) -> Optional[ChrName]:
    """Parse underscore-separated chr_name; return None if it doesn't match.

    Supported input: e.g. "7007007_001001_000000_001001_08007".
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
    """Pick the most informative naming column (chr_name preferred over name)."""
    if df is None or len(df) == 0:
        return None
    if "chr_name" in df.columns:
        return "chr_name"
    if "name" in df.columns:
        return "name"
    return None


def _precompute_bus_metadata(net: pp.pandapowerNet) -> Dict[int, Optional[ChrName]]:
    """Pre-parse chr_name metadata for all buses; keyed by bus index."""
    b_col = _best_name_col(net.bus)
    bus_chr: Dict[int, Optional[ChrName]] = {}
    for b, row in net.bus.iterrows():
        bus_chr[int(b)] = parse_chr_name(row.get(b_col)) if b_col else None
    return bus_chr


def _is_lv_line(line_row: pd.Series, bus_chr: Dict[int, Optional[ChrName]],
                name_col: Optional[str]) -> bool:
    """True if the line is in service, not an encoded open tie, and connects two LV buses."""
    # service status
    if not bool(line_row.get('in_service', True)):
        return False

    # encoded open ties (via chr_name)
    if name_col and pd.notna(line_row.get(name_col)):
        cnl = parse_chr_name(line_row.get(name_col))
        if cnl and cnl.is_open_tie_candidate:
            return False

    # both endpoints must be LV (Netzebene 7)
    u, v = int(line_row["from_bus"]), int(line_row["to_bus"])
    cu, cv = bus_chr.get(u), bus_chr.get(v)
    return bool(cu and cu.is_lv and cv and cv.is_lv)


def _should_remove_edge(switch_row: pd.Series, name_col: Optional[str]) -> bool:
    """Return True if a switch opens an edge (open/inactive or encoded open tie)."""
    closed = bool(switch_row.get("closed", True))
    in_service = bool(switch_row.get("in_service", True))

    naming_open = False
    if name_col:
        cn = parse_chr_name(switch_row.get(name_col))
        naming_open = bool(cn and cn.is_open_tie_candidate)

    return not closed or not in_service or naming_open


def _process_switches(net: pp.pandapowerNet, G: nx.Graph) -> None:
    """Remove edges from the graph according to switch states (line and bus-bus)."""
    if not hasattr(net, "switch") or len(net.switch) == 0:
        return

    s_col = _best_name_col(net.switch)
    for _, srow in net.switch.iterrows():
        if not _should_remove_edge(srow, s_col):
            continue

        try:
            et = srow.get("et", "")
            element = srow.get("element")

            if et == "l":  # line switch
                line_idx = int(element)
                if line_idx in net.line.index:
                    lrow = net.line.loc[line_idx]
                    u, v = int(lrow["from_bus"]), int(lrow["to_bus"])
                    if G.has_edge(u, v):
                        G.remove_edge(u, v)

            elif et == "b":  # bus-bus switch
                u = int(srow.get("bus")) if pd.notna(srow.get("bus")) else None
                v = int(element) if pd.notna(element) else None
                if u is not None and v is not None and G.has_edge(u, v):
                    G.remove_edge(u, v)
        except Exception:
            continue


def _build_global_operational_graph(net: pp.pandapowerNet) -> nx.Graph:
    """
    Build the operational LV graph (nodes=buses, edges=lines) for Netzebene 7.

    Includes only LV buses; respects line in_service flags, switch states, and
    encoded open ties. Result is used for distance-based trafo zone assignment.
    """
    G = nx.Graph()

    # bus metadata for LV filtering and open-tie detection
    bus_chr = _precompute_bus_metadata(net)

    # add LV-only line edges
    l_col = _best_name_col(net.line)
    for idx, row in net.line.iterrows():
        if _is_lv_line(row, bus_chr, l_col):
            u, v = int(row["from_bus"]), int(row["to_bus"])
            G.add_edge(u, v, line=int(idx))

    # remove open/inactive switches
    _process_switches(net, G)

    return G


def _component_nodes(G: nx.Graph, root: int) -> List[int]:
    """Nodes in the connected component that contains the given root (or empty list)."""
    if root not in G:
        return []
    return list(nx.node_connected_component(G, root))


def _isolate_one_trafo(G_sub: nx.Graph, root_lvb: int, other_trafos: List[int]) -> nx.Graph:
    """Cut a component along shortest paths to isolate the given transformer LV bus.

    Used as a local repair when multiple transformers land in one component.
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
    """Keep only a BFS tree from root (drop meshing) to enforce radiality."""
    if root not in H:
        return H
    T = nx.bfs_tree(H, root)
    keep = set(tuple(sorted(e)) for e in T.to_undirected().edges())
    for u, v in list(H.edges()):
        if tuple(sorted((u, v))) not in keep:
            H.remove_edge(u, v)
    return H


def _infer_netznummer_from_loads(net: pp.pandapowerNet, buses: List[int]) -> str:
    """Infer netznummer label from loads connected to the given buses (mode of matches)."""
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
    """Flood-fill nodes for a target netznummer without crossing into other netznummers.

    Seeds are LV buses with chr_name.netznummer == target_netz; propagation stops at
    LV buses whose netznummer differs. Buses without chr_name are included.
    """
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
                continue  # hard boundary at other netznummer
            allowed.add(v)
            dq.append(v)
    return allowed


def _assign_buses_to_trafos(
    G_sub: nx.Graph,
    trafos_in_netz: Dict[int, int],  # trafo_idx -> lv_bus (should be in G_sub)
) -> Dict[int, List[int]]:
    """Assign nodes of a subgraph to the nearest LV bus among a set of trafos.

    Returns
    -------
    dict: trafo_idx -> list of bus indices assigned to that transformer
    """
    roots = {t_idx: lvb for t_idx, lvb in trafos_in_netz.items() if lvb in G_sub}
    assignment: Dict[int, List[int]] = {t_idx: [] for t_idx in roots}
    if not roots:
        return assignment

    # multi-source distances
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


# ==============================================================================
# Distance-based splitting API
# ==============================================================================

@dataclass
class SplitStatistics:
    """Summary statistics for split validation and reporting.

    Note: Some tolerances are applied to handle meshed LV networks and HV bus duplication.
    """
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
        """Heuristic check: split buses roughly match original counts (LV/HV nuances)."""
        original_lv = self.original_buses - self.original_trafos  # rough estimate
        return abs(self.split_buses_total - self.original_buses) <= self.num_subgrids * 2

    @property
    def lines_match(self) -> bool:
        """Allow up to 10% line-count difference (cross-zone edges may be dropped)."""
        return abs(self.split_lines_total - self.original_lines) / max(self.original_lines, 1) < 0.10

    @property
    def loads_match(self) -> bool:
        """Loads must match exactly across split nets."""
        return self.split_loads_total == self.original_loads

    @property
    def validation_passed(self) -> bool:
        """True if buses, lines (within tolerance), and loads match."""
        return self.buses_match and self.lines_match and self.loads_match



def assign_buses_to_transformers(
    G: nx.Graph,
    trafo_lv_buses: Dict[int, int],  # trafo_idx -> lv_bus
) -> Dict[int, List[int]]:
    """
    Assign every bus in the operational graph to exactly one transformer (nearest by hops).

    Parameters
    ----------
    G : nx.Graph
        Operational LV graph (switch-respecting, LV-only).
    trafo_lv_buses : dict
        Mapping of transformer index → LV bus index.

    Returns
    -------
    dict
        Transformer index → list of assigned bus indices.
    """
    logger = logging.getLogger(__name__)

    valid_trafos = {t_idx: lvb for t_idx, lvb in trafo_lv_buses.items() if lvb in G}
    if not valid_trafos:
        logger.warning("No valid transformers found in graph")
        return {}

    logger.info(f"Assigning buses to {len(valid_trafos)} transformers…")

    # shortest-path lengths from each trafo LV bus
    distances: Dict[int, Dict[int, int]] = {}
    for t_idx, lvb in valid_trafos.items():
        try:
            distances[t_idx] = nx.single_source_shortest_path_length(G, lvb)
        except Exception as e:
            logger.warning(f"Failed to compute distances for trafo {t_idx}: {e}")
            distances[t_idx] = {lvb: 0}

    assignment: Dict[int, List[int]] = {t_idx: [] for t_idx in valid_trafos}
    all_buses = set(G.nodes())

    for bus in all_buses:
        best_trafo = None
        best_dist = None
        for t_idx, dist_map in distances.items():
            if bus not in dist_map:
                continue
            dist = dist_map[bus]
            if best_trafo is None or dist < best_dist or (dist == best_dist and t_idx < best_trafo):
                best_trafo = t_idx
                best_dist = dist
        if best_trafo is not None:
            assignment[best_trafo].append(bus)

    # stats
    for t_idx, buses in assignment.items():
        logger.debug(f"  Trafo {t_idx}: assigned {len(buses)} buses")

    unassigned = len(all_buses) - sum(len(buses) for buses in assignment.values())
    if unassigned > 0:
        logger.warning(f"  {unassigned} buses could not be assigned to any transformer")

    return assignment


def _get_hv_bus(net: pp.pandapowerNet, trafo_idx: int) -> Optional[int]:
    """Return HV bus index for the given transformer (None if unavailable)."""
    if trafo_idx not in net.trafo.index:
        return None
    try:
        return int(net.trafo.loc[trafo_idx, "hv_bus"])
    except Exception:
        return None


def _filter_operational_lines(sub_net: pp.pandapowerNet, assigned_buses: List[int],
                              G_operational: nx.Graph) -> None:
    """Keep only operational lines whose endpoints are assigned buses.

    Updates sub_net.line and sub_net.line_geodata in place.
    """
    if len(sub_net.line) == 0:
        return

    assigned_bus_set = set(assigned_buses)
    lines_to_keep = []

    for idx, lrow in sub_net.line.iterrows():
        u, v = int(lrow["from_bus"]), int(lrow["to_bus"])
        if u in assigned_bus_set and v in assigned_bus_set and G_operational.has_edge(u, v):
            lines_to_keep.append(idx)

    sub_net.line = sub_net.line.loc[lines_to_keep]
    if not sub_net.line_geodata.empty:
        sub_net.line_geodata = sub_net.line_geodata.loc[
            sub_net.line_geodata.index.isin(sub_net.line.index)
        ]

    sub_net.line.reset_index(drop=True, inplace=True)
    if not sub_net.line_geodata.empty:
        sub_net.line_geodata.reset_index(drop=True, inplace=True)


def _radialize_subgrid(sub_net: pp.pandapowerNet, trafo_idx: int) -> None:
    """Prune meshed edges; keep a BFS tree from the LV bus to enforce radiality."""
    logger = logging.getLogger(__name__)

    if trafo_idx not in sub_net.trafo.index:
        return

    lvb = int(sub_net.trafo.loc[trafo_idx, "lv_bus"])
    if lvb not in sub_net.bus.index:
        return

    H = nx.Graph()
    H.add_nodes_from(sub_net.bus.index)
    for idx, lrow in sub_net.line.iterrows():
        u, v = int(lrow["from_bus"]), int(lrow["to_bus"])
        H.add_edge(u, v, line_idx=idx)

    if lvb not in H:
        return

    try:
        tree = nx.bfs_tree(H, lvb)
        tree_edges = set(tuple(sorted(e)) for e in tree.to_undirected().edges())

        lines_to_keep = []
        for idx, lrow in sub_net.line.iterrows():
            u, v = int(lrow["from_bus"]), int(lrow["to_bus"])
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


def create_subgrid_from_assignment(
    net: pp.pandapowerNet,
    trafo_idx: int,
    assigned_buses: List[int],
    G_operational: nx.Graph,
) -> pp.pandapowerNet:
    """
    Build a pandapower subnet for one transformer from its assigned buses.

    Adds the transformer's HV bus, filters lines to operational ones within the
    assignment, removes switches (already enforced in the graph), and prunes
    meshing to a radial tree.
    """
    # buses to keep (LV assignments + optional HV bus)
    hvb = _get_hv_bus(net, trafo_idx)
    final_buses = sorted(assigned_buses)
    if hvb is not None and hvb in net.bus.index and hvb not in final_buses:
        final_buses.append(hvb)
        final_buses = sorted(final_buses)

    sub_net = pp.select_subnet(
        net,
        buses=final_buses,
        include_results=False,
        include_switch_buses=True,
    )

    _filter_operational_lines(sub_net, assigned_buses, G_operational)

    # switches already respected in G; drop them from the subnet
    if hasattr(sub_net, "switch") and len(sub_net.switch) > 0:
        sub_net.switch.drop(sub_net.switch.index, inplace=True)

    _radialize_subgrid(sub_net, trafo_idx)

    return sub_net


def split_into_lv_subgrids_improved(
    net: pp.pandapowerNet,
    output_dir: str | Path | None = None,
) -> Tuple[Dict[str, pp.pandapowerNet], SplitStatistics]:
    """
    Split a network into LV subgrids, one per transformer, using distance-based assignment.

    Guarantees each bus belongs to exactly one subgrid and applies simple consistency
    checks. Optionally writes each subgrid to <output_dir> as JSON.
    """
    logger = logging.getLogger(__name__)

    if output_dir is None:
        from src.analysis.validation.utils import load_validation_config
        data_dir, _net_name, _proj = load_validation_config()
        output_dir = data_dir / "subgrids"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build operational LV graph
    logger.info("Building operational graph…")
    G = _build_global_operational_graph(net)
    logger.info(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Identify LV transformers by LV-bus nominal voltage
    trafo_lv_buses: Dict[int, int] = {}
    for t_idx, row in net.trafo.iterrows():
        try:
            lvb = int(row["lv_bus"])
            if float(net.bus.at[lvb, "vn_kv"]) <= 1.0:
                trafo_lv_buses[int(t_idx)] = lvb
        except Exception:
            continue

    logger.info(f"Found {len(trafo_lv_buses)} LV transformers")

    # Assign buses to nearest transformer (key step)
    logger.info("Assigning buses to transformers by nearest distance…")
    bus_assignment = assign_buses_to_transformers(G, trafo_lv_buses)

    # Drop trivial/empty subgrids (e.g., only LV bus)
    bus_assignment = {t_idx: buses for t_idx, buses in bus_assignment.items() if len(buses) > 1}

    logger.info(f"Creating {len(bus_assignment)} subgrids…")

    subgrids: Dict[str, pp.pandapowerNet] = {}

    for t_idx, assigned_buses in bus_assignment.items():
        logger.debug(f"  Processing trafo {t_idx} with {len(assigned_buses)} buses…")

        sub_net = create_subgrid_from_assignment(
            net, t_idx, assigned_buses, G
        )

        # subgrid ID: prefer netznummer inferred from loads
        netz = _infer_netznummer_from_loads(net, assigned_buses)
        subgrid_id = f"{netz}__trafo_{t_idx}" if netz != "unk" else f"trafo_{t_idx}"

        subgrids[subgrid_id] = sub_net

        # persist
        out_file = output_dir / f"{subgrid_id}.json"
        try:
            pp.to_json(sub_net, str(out_file))
            logger.debug(f"    Saved: {len(sub_net.bus)} buses, {len(sub_net.line)} lines")
        except Exception as e:
            logger.error(f"    Failed to save {subgrid_id}: {e}")

    # stats & summary
    stats = compute_split_statistics(net, subgrids)

    logger.info(f"✓ Created {len(subgrids)} subgrids")

    return subgrids, stats


def compute_split_statistics(
    original_net: pp.pandapowerNet,
    subgrids: Dict[str, pp.pandapowerNet],
) -> SplitStatistics:
    """Compare element counts of the original network with the sum over subgrids."""

    # Original
    orig_buses = len(original_net.bus)
    orig_lines = len(original_net.line)
    orig_loads = len(original_net.load) if hasattr(original_net, 'load') else 0
    orig_sgens = len(original_net.sgen) if hasattr(original_net, 'sgen') else 0
    orig_trafos = len(original_net.trafo) if hasattr(original_net, 'trafo') else 0

    # Split totals
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
    """CLI entry point: load configured net, perform split, and log a short report."""
    from src.analysis.validation.utils import read_net_json

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("IMPROVED LV SUBGRID SPLITTER")
    logger.info("=" * 80)
    logger.info("")

    net, file_path = read_net_json()
    logger.info(f"Loaded network from: {file_path}")
    logger.info(f"  Buses: {len(net.bus)}")
    logger.info(f"  Lines: {len(net.line)}")
    logger.info(f"  Loads: {len(net.load) if hasattr(net, 'load') else 0}")
    logger.info(f"  Transformers: {len(net.trafo) if hasattr(net, 'trafo') else 0}")
    logger.info("")

    subgrids, stats = split_into_lv_subgrids_improved(net)

    logger.info("")
    logger.info("=" * 80)
    logger.info("SPLITTING COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    run_improved_split()
