"""
Paper network visualisation using pyvis.

Two network types:
  citation   — directed edges when paper A cites paper B (both in corpus)
  similarity — undirected edges connecting each paper's k nearest neighbours
               by embedding cosine similarity

Important papers (top_n) are highlighted in red based on:
  citation   — in-degree (most cited within the corpus)
  similarity — degree (most connected to similar papers)
"""
from __future__ import annotations

import json
import textwrap
from collections import defaultdict
from typing import Literal

import numpy as np

# Colour palette for up to 12 clusters
_CLUSTER_COLORS = [
    "#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6",
    "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16",
    "#06B6D4", "#A855F7",
]
_NOISE_COLOR = "#64748B"
_IMPORTANT_COLOR = {"background": "#EF4444", "border": "#7F1D1D",
                    "highlight": {"background": "#F87171", "border": "#EF4444"}}


def _cluster_color(cluster_id) -> str:
    if cluster_id is None or int(cluster_id) < 0:
        return _NOISE_COLOR
    return _CLUSTER_COLORS[int(cluster_id) % len(_CLUSTER_COLORS)]


def _node_size(relevance_score) -> float:
    s = relevance_score or 30.0
    return max(8.0, min(55.0, s * 0.55))


def _tooltip(p: dict, connections: int = 0, is_important: bool = False) -> str:
    try:
        authors = [a["name"] for a in json.loads(p.get("authors") or "[]")][:3]
        author_str = ", ".join(authors) or "Unknown"
    except Exception:
        author_str = "Unknown"
    title = textwrap.fill(p.get("title", "?"), width=50)
    important_badge = "<br><b style='color:#FCA5A5'>⭐ Key paper in this corpus</b>" if is_important else ""
    return (
        f"<b>{title}</b><br>"
        f"<i>{author_str}</i><br>"
        f"Year: {p.get('year', '?')} &nbsp;|&nbsp; "
        f"Citations: {p.get('citation_count', 0)}<br>"
        f"Relevance: {p.get('relevance_score') or 0:.1f} / 100<br>"
        f"Cluster: {p.get('cluster_label') or 'Uncategorised'}<br>"
        f"Network connections: {connections}"
        f"{important_badge}"
    )


_PHYSICS_OPTIONS = """
{
  "physics": {
    "enabled": true,
    "solver": "forceAtlas2Based",
    "forceAtlas2Based": {
      "gravitationalConstant": -60,
      "centralGravity": 0.003,
      "springLength": 180,
      "springConstant": 0.05,
      "damping": 0.4
    },
    "stabilization": { "iterations": 200, "updateInterval": 25 }
  },
  "interaction": {
    "hover": true,
    "tooltipDelay": 120,
    "navigationButtons": true,
    "keyboard": { "enabled": true }
  },
  "edges": {
    "smooth": { "type": "continuous" },
    "color": { "opacity": 0.55 }
  }
}
"""


def build_network(
    papers: list[dict],
    network_type: Literal["citation", "similarity"] = "citation",
    max_nodes: int = 120,
    similarity_k: int = 4,
    similarity_threshold: float = 0.55,
    embedding_map: dict[str, list[float]] | None = None,
    top_n: int = 10,
) -> tuple[str, int, int, list[dict]]:
    """
    Build a pyvis network HTML.

    Returns (html_string, n_nodes, n_edges, important_papers).
    important_papers is a list of paper dicts (with added '_connections' key)
    sorted by network centrality, length <= top_n.
    """
    from pyvis.network import Network

    # Sort by relevance and cap
    sorted_papers = sorted(
        papers,
        key=lambda p: p.get("relevance_score") or 0,
        reverse=True,
    )[:max_nodes]

    paper_id_set = {p["id"] for p in sorted_papers}

    # ── Step 1: Pre-compute edge list and centrality ────────────────────────────
    # centrality[paper_id] = number of incoming (citation) or total (similarity) edges
    centrality: dict[str, int] = defaultdict(int)
    edge_list: list[tuple] = []  # (src_id, tgt_id, kwargs)

    if network_type == "citation":
        oa_to_id = {
            p["openalex_id"]: p["id"]
            for p in sorted_papers
            if p.get("openalex_id")
        }
        for p in sorted_papers:
            try:
                refs = json.loads(p.get("referenced_works") or "[]")
            except Exception:
                refs = []
            for ref_oa_id in refs:
                cited_id = oa_to_id.get(ref_oa_id)
                if cited_id and cited_id != p["id"]:
                    edge_list.append((
                        p["id"], cited_id,
                        {"arrows": "to", "width": 1.2, "color": {"color": "#94A3B8"}},
                    ))
                    centrality[cited_id] += 1  # in-degree

    elif network_type == "similarity":
        if not embedding_map:
            # Return node-only graph — no centrality available
            net = Network(height="660px", width="100%", bgcolor="#1E293B",
                          font_color="#F1F5F9", directed=False)
            for p in sorted_papers:
                short_label = (p.get("title") or "?")[:38]
                if len(p.get("title") or "") > 38:
                    short_label += "…"
                net.add_node(p["id"], label=short_label, title=_tooltip(p),
                             size=_node_size(p.get("relevance_score")),
                             color=_cluster_color(p.get("cluster_id")),
                             borderWidth=2, font={"size": 11, "color": "#F1F5F9"})
            net.set_options(_PHYSICS_OPTIONS)
            return net.generate_html(), len(sorted_papers), 0, []

        ids = [p["id"] for p in sorted_papers if p["id"] in embedding_map]
        if len(ids) < 2:
            net = Network(height="660px", width="100%", bgcolor="#1E293B",
                          font_color="#F1F5F9", directed=False)
            for p in sorted_papers:
                short_label = (p.get("title") or "?")[:38]
                if len(p.get("title") or "") > 38:
                    short_label += "…"
                net.add_node(p["id"], label=short_label, title=_tooltip(p),
                             size=_node_size(p.get("relevance_score")),
                             color=_cluster_color(p.get("cluster_id")),
                             borderWidth=2, font={"size": 11, "color": "#F1F5F9"})
            net.set_options(_PHYSICS_OPTIONS)
            return net.generate_html(), len(sorted_papers), 0, []

        X = np.array([embedding_map[pid] for pid in ids], dtype=np.float32)
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        X_norm = X / (norms + 1e-9)
        sim_matrix = X_norm @ X_norm.T

        added_edges: set[frozenset] = set()
        for i, src_id in enumerate(ids):
            row = sim_matrix[i].copy()
            row[i] = -1.0
            top_k_idx = np.argsort(row)[-similarity_k:]
            for j in top_k_idx:
                if row[j] < similarity_threshold:
                    continue
                tgt_id = ids[j]
                edge_key = frozenset([src_id, tgt_id])
                if edge_key in added_edges:
                    continue
                added_edges.add(edge_key)
                width = round(float((row[j] - similarity_threshold) / (1 - similarity_threshold) * 4 + 1), 2)
                edge_list.append((
                    src_id, tgt_id,
                    {"width": width, "color": {"color": "#60A5FA"},
                     "title": f"Similarity: {row[j]:.2f}"},
                ))
                centrality[src_id] += 1  # undirected degree
                centrality[tgt_id] += 1

    # ── Step 2: Identify top_n important papers (must have ≥1 connection) ──────
    connected_ids = {pid for pid in paper_id_set if centrality.get(pid, 0) > 0}
    top_ids = set(
        sorted(connected_ids, key=lambda pid: centrality[pid], reverse=True)[:top_n]
    )

    # ── Step 3: Build network with coloured nodes ───────────────────────────────
    directed = network_type == "citation"
    net = Network(
        height="660px",
        width="100%",
        bgcolor="#1E293B",
        font_color="#F1F5F9",
        directed=directed,
    )

    for p in sorted_papers:
        is_important = p["id"] in top_ids
        connections = centrality.get(p["id"], 0)
        short_label = (p.get("title") or "?")[:38]
        if len(p.get("title") or "") > 38:
            short_label += "…"
        net.add_node(
            p["id"],
            label=short_label,
            title=_tooltip(p, connections=connections, is_important=is_important),
            size=_node_size(p.get("relevance_score")) * (1.4 if is_important else 1.0),
            color=_IMPORTANT_COLOR if is_important else _cluster_color(p.get("cluster_id")),
            borderWidth=4 if is_important else 2,
            font={"size": 13 if is_important else 11, "color": "#F1F5F9",
                  "bold": is_important},
        )

    for src_id, tgt_id, kwargs in edge_list:
        net.add_edge(src_id, tgt_id, **kwargs)

    net.set_options(_PHYSICS_OPTIONS)

    # ── Step 4: Build sorted important_papers list ──────────────────────────────
    id_to_paper = {p["id"]: p for p in sorted_papers}
    important_papers = []
    for pid in sorted(top_ids, key=lambda pid: centrality[pid], reverse=True):
        p = dict(id_to_paper[pid])  # copy so we don't mutate the original
        p["_connections"] = centrality[pid]
        important_papers.append(p)

    return net.generate_html(), len(sorted_papers), len(edge_list), important_papers
