from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pandapower as pp
import networkx as nx
import logging

# --------------------------------------------------------------------------------------
# Naming parser (underscore-separated variant only)
# --------------------------------------------------------------------------------------

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
    - Restrict to LV-only connectivity: edges between buses whose chr_name indicates LV (lvl==7);
      if chr_name missing/unparseable, fall back to vn_kv <= 1.0 kV
     """
    G = nx.Graph()
    G.add_nodes_from(net.bus.index.tolist())

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
        # Only LV-LV edges based on chr_name lvl==7 when available else vn_kv fallback
        cu, cv = bus_chr.get(u), bus_chr.get(v)
        is_lv_u = (cu.is_lv if cu else (float(bus_vn.get(u, 99)) <= 1.0))
        is_lv_v = (cv.is_lv if cv else (float(bus_vn.get(v, 99)) <= 1.0))
        if not (is_lv_u and is_lv_v):
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


def split_into_operational_lv_subgrids(
    net: pp.pandapowerNet,
    output_dir: str | Path = "grid_data/subgrids/SWF_V7",
) -> Dict[str, pp.pandapowerNet]:
    """Split the provided pandapower net into operationally radial LV subgrids per transformer.

    Writes each subgrid as a pandapower JSON to output_dir. Returns a dict of {subgrid_id: net}.

    FIXED APPROACH:
    - Build operational graph with all LV buses and lines
    - For each transformer, do BFS from its LV bus to find all reachable buses
    - Stop BFS at other transformer LV buses to ensure one transformer per subgrid
    - Radialize the resulting subgraph
    - Only include buses that have lines connecting them in the final radial tree
    """
    logger = logging.getLogger(__name__)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Global operational graph (lines + switch-open removals)
    G = _build_global_operational_graph(net)
    logger.info(f"Built operational graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Pre-parse bus chr for later naming
    bus_chr: Dict[int, Optional[ChrName]] = {}
    b_col = _best_name_col(net.bus)
    if b_col:
        for b, row in net.bus.iterrows():
            bus_chr[int(b)] = parse_chr_name(row.get(b_col))
    else:
        bus_chr = {int(b): None for b in net.bus.index}

    # Collect all trafo LV buses
    trafo_lv_buses: Dict[int, int] = {}
    for t_idx, row in net.trafo.iterrows():
        try:
            lvb = int(row["lv_bus"])
            # only LV trafos (lv bus nominal voltage <= 1 kV)
            if float(net.bus.at[lvb, "vn_kv"]) <= 1.0:
                trafo_lv_buses[int(t_idx)] = lvb
        except Exception:
            continue

    logger.info(f"Found {len(trafo_lv_buses)} LV transformers")
    outputs: Dict[str, pp.pandapowerNet] = {}

    # Process each transformer independently
    trafo_lv_bus_set = set(trafo_lv_buses.values())

    for t_idx, lvb in trafo_lv_buses.items():
        if lvb not in G:
            logger.warning(f"Trafo {t_idx} LV bus {lvb} not in graph, skipping")
            continue

        # BFS from this transformer's LV bus, stopping at other transformer LV buses
        from collections import deque
        visited = set()
        queue = deque([lvb])
        visited.add(lvb)

        while queue:
            u = queue.popleft()
            for v in G.neighbors(u):
                if v in visited:
                    continue
                # Stop at other transformer LV buses (boundaries)
                if v in trafo_lv_bus_set and v != lvb:
                    continue
                visited.add(v)
                queue.append(v)

        buses = sorted(visited)
        if len(buses) < 2:  # Only LV bus itself
            logger.warning(f"Trafo {t_idx} has only {len(buses)} bus(es), skipping")
            continue

        # Build induced subgraph and radialize
        H_full = G.subgraph(buses).copy()
        H = _radialize(H_full, lvb)

        # Keep only the root component after radialization
        if lvb in H:
            root_comp_nodes = list(nx.node_connected_component(H, lvb))
            H = H.subgraph(root_comp_nodes).copy()
            # Only include buses that are in the radial tree (connected via edges)
            buses_in_tree = set(root_comp_nodes)
        else:
            buses_in_tree = {lvb}

        # Include HV bus for trafo consistency (even though not in LV tree)
        hvb = None
        try:
            hvb = int(net.trafo.loc[t_idx, "hv_bus"]) if "hv_bus" in net.trafo.columns else None
        except Exception:
            hvb = None

        final_buses = sorted(buses_in_tree)
        if hvb is not None and hvb in net.bus.index and hvb not in final_buses:
            final_buses.append(hvb)
            final_buses = sorted(final_buses)

        # Create subnetwork selecting the trafo element as well
        try:
            sub_net = pp.select_subnet(
                net,
                buses=final_buses,
                include_results=False,
                include_switch_buses=True,
            )
        except TypeError:
            sub_net = pp.select_subnet(net, buses=final_buses, include_results=False, include_switch_buses=True)

        # Post-process: keep only radial line edges corresponding to H
        try:
            allowed_edges = set(tuple(sorted(e)) for e in H.edges())
            if len(sub_net.line) > 0:
                mask = []
                for _, lrow in sub_net.line.iterrows():
                    u = int(lrow["from_bus"]); v = int(lrow["to_bus"])
                    mask.append(tuple(sorted((u, v))) in allowed_edges)
                sub_net.line = sub_net.line.loc[pd.Series(mask, index=sub_net.line.index)]
                sub_net.line.reset_index(drop=True, inplace=True)
            if hasattr(sub_net, "switch") and len(sub_net.switch) > 0:
                sub_net.switch.drop(sub_net.switch.index, inplace=True)
        except Exception as e:
            logger.warning(f"Error filtering lines for trafo {t_idx}: {e}")

        # Filename based on loads in this assignment
        netz_out = _infer_netznummer_from_loads(net, final_buses)
        subgrid_id = f"{netz_out}__trafo_{t_idx}" if netz_out != "unk" else f"trafo_{t_idx}"
        out_file = Path(output_dir) / f"{subgrid_id}.json"
        # Remove stale files for this trafo id (different prefixes)
        try:
            for stale in Path(output_dir).glob(f"*__trafo_{t_idx}.json"):
                if stale.name != out_file.name:
                    stale.unlink(missing_ok=True)
            # Also remove bare trafo_{id}.json if writing a prefixed one
            bare = Path(output_dir) / f"trafo_{t_idx}.json"
            if bare.exists() and bare.name != out_file.name:
                bare.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            pp.to_json(sub_net, str(out_file))
            logger.debug(f"Wrote trafo {t_idx}: {len(final_buses)-1} LV buses, {H.number_of_edges()} lines")
        except Exception as e:
            logger.error(f"Failed to write trafo {t_idx}: {e}")
            out_file = Path(output_dir) / f"trafo_{t_idx}.json"
            pp.to_json(sub_net, str(out_file))
        outputs[subgrid_id] = sub_net

    logger.info(f"Created {len(outputs)} subgrids")
    return outputs


def run_split(
    json_path: str = "grid_data/SWF_V7.json",
    output_dir: str = "grid_data/subgrids/SWF_V7",
) -> None:
    """Run the splitter against a pandapower JSON and write subgrids only."""
    net = pp.from_json(json_path)
    split_into_operational_lv_subgrids(net, output_dir=output_dir)

