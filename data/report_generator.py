"""Assemble a self-contained HTML dashboard report of a completed literature review."""
from __future__ import annotations

import copy
import html
import json
import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from utils.prisma import PRISMAData, build_prisma_figure

# Change to True to bundle Plotly JS inline (~3.5 MB) for fully offline reports.
PLOTLYJS_STRATEGY: str | bool = "cdn"

_REPORT_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.6; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
header { background: #1e293b; color: #f1f5f9; padding: 2rem; }
header h1 { font-size: 1.8rem; margin-bottom: .5rem; }
header .meta { font-size: .85rem; color: #94a3b8; margin-bottom: .4rem; }
header .rq { font-size: 1rem; color: #cbd5e1; }
nav#toc { background: #fff; border-bottom: 1px solid #e2e8f0; padding: 1rem 2rem; }
nav#toc h2 { font-size: .85rem; text-transform: uppercase; color: #64748b; letter-spacing: .05em; margin-bottom: .4rem; }
nav#toc ol { display: flex; gap: 1.5rem; list-style: none; flex-wrap: wrap; }
nav#toc ol li a { font-size: .9rem; color: #475569; }
section { background: #fff; margin: 1.5rem 2rem; border-radius: 8px; padding: 1.5rem 2rem;
          box-shadow: 0 1px 3px rgba(0,0,0,.07); }
section h2 { font-size: 1.25rem; color: #1e293b; margin-bottom: 1rem; padding-bottom: .5rem;
             border-bottom: 2px solid #e2e8f0; }
section h3 { font-size: 1rem; color: #334155; margin: 1rem 0 .4rem; }
.placeholder { background: #f1f5f9; border: 2px dashed #cbd5e1; border-radius: 6px;
               padding: 2rem; text-align: center; color: #64748b; font-size: .95rem; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 800px) { .chart-grid { grid-template-columns: 1fr; } }
.synth-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
@media (max-width: 800px) { .synth-cols { grid-template-columns: 1fr; } }
.synth-cols ul { padding-left: 1.2rem; }
.synth-cols ul li { margin-bottom: .3rem; }
details.cluster { border: 1px solid #e2e8f0; border-radius: 6px; margin-bottom: .5rem; }
details.cluster summary { padding: .6rem 1rem; cursor: pointer; font-weight: 600; background: #f8fafc;
                           border-radius: 6px; list-style: none; }
details.cluster summary::-webkit-details-marker { display: none; }
details.cluster summary::before { content: "▶  "; font-size: .75rem; color: #64748b; }
details.cluster[open] summary::before { content: "▼  "; }
details.cluster > div { padding: .75rem 1rem; font-size: .92rem; color: #475569; }
table.paper-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
table.paper-table th { background: #f1f5f9; padding: .5rem .75rem; text-align: left;
                        border-bottom: 2px solid #e2e8f0; cursor: pointer; user-select: none;
                        white-space: nowrap; }
table.paper-table th:hover { background: #e2e8f0; }
table.paper-table th.sort-asc::after { content: " ▲"; font-size: .7rem; }
table.paper-table th.sort-desc::after { content: " ▼"; font-size: .7rem; }
table.paper-table td { padding: .45rem .75rem; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
table.paper-table tr:hover td { background: #f8fafc; }
.rel-bar { display: inline-block; height: 8px; border-radius: 4px; background: #3b82f6; min-width: 2px; }
footer { text-align: center; padding: 2rem; color: #94a3b8; font-size: .8rem; }
"""

_SORT_JS = """
(function() {
  var tables = document.querySelectorAll('table.paper-table');
  tables.forEach(function(tbl) {
    var headers = tbl.querySelectorAll('th');
    var sortState = { col: -1, dir: 1 };
    headers.forEach(function(th, idx) {
      th.addEventListener('click', function() {
        var dir = (sortState.col === idx) ? -sortState.dir : -1;
        sortState = { col: idx, dir: dir };
        headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
        th.classList.add(dir === -1 ? 'sort-desc' : 'sort-asc');
        var tbody = tbl.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {
          var av = a.cells[idx] ? a.cells[idx].innerText.trim() : '';
          var bv = b.cells[idx] ? b.cells[idx].innerText.trim() : '';
          var an = parseFloat(av), bn = parseFloat(bv);
          if (!isNaN(an) && !isNaN(bn)) return dir * (bn - an);
          return dir * av.localeCompare(bv);
        });
        rows.forEach(function(r) { tbody.appendChild(r); });
      });
    });
  });
})();
"""


def _fig_to_div(fig: go.Figure, first: bool = False) -> str:
    """Serialise a Plotly figure to an HTML div. PlotlyJS CDN injected only on first call."""
    fig_copy = copy.deepcopy(fig)
    fig_copy.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc")
    include_js = PLOTLYJS_STRATEGY if first else False
    return pio.to_html(fig_copy, full_html=False, include_plotlyjs=include_js, config={"responsive": True})


def _build_cluster_fig(included: list[dict], synthesis: dict) -> go.Figure | None:
    coords = synthesis.get("coords_2d") or []
    paper_ids = synthesis.get("paper_ids") or []
    if not coords or not paper_ids:
        return None
    id_to_paper = {p["id"]: p for p in included}
    rows = []
    for pid, (x, y) in zip(paper_ids, coords):
        p = id_to_paper.get(pid, {})
        try:
            authors = [a["name"] for a in json.loads(p.get("authors") or "[]")]
            author_str = ", ".join(authors[:2])
        except Exception:
            author_str = ""
        rows.append({
            "x": x, "y": y,
            "title": p.get("title", "?"),
            "cluster": p.get("cluster_label", "Uncategorised"),
            "year": p.get("year", ""),
            "citations": p.get("citation_count", 0),
            "author": author_str,
        })
    df = pd.DataFrame(rows)
    fig = px.scatter(
        df, x="x", y="y", color="cluster",
        hover_data={"title": True, "author": True, "year": True, "citations": True, "x": False, "y": False},
        title="Paper clusters (2D projection of semantic embeddings)",
        labels={"x": "Dimension 1", "y": "Dimension 2"},
    )
    fig.update_traces(marker=dict(size=10, opacity=0.8))
    fig.update_layout(legend_title="Cluster")
    return fig


def _build_stats_figs(included: list[dict]) -> dict[str, go.Figure | None]:
    figs: dict[str, go.Figure | None] = {"year": None, "journal": None, "quality": None, "citations": None}
    if not included:
        return figs

    year_counts = pd.Series([p.get("year") for p in included if p.get("year")]).value_counts().sort_index()
    if not year_counts.empty:
        figs["year"] = px.bar(x=year_counts.index.tolist(), y=year_counts.values.tolist(),
                               labels={"x": "Year", "y": "Papers"}, title="Papers by Year")

    journal_counts = (
        pd.Series([p.get("journal") for p in included if p.get("journal")])
        .value_counts().head(15)
    )
    if not journal_counts.empty:
        figs["journal"] = px.bar(x=journal_counts.values.tolist(), y=journal_counts.index.tolist(),
                                  orientation="h", labels={"x": "Papers", "y": "Journal"}, title="Top Journals")

    quality_scores = [p.get("quality_score") for p in included if p.get("quality_score")]
    if quality_scores:
        figs["quality"] = px.histogram(x=quality_scores, nbins=20,
                                        labels={"x": "Quality Score", "y": "Count"},
                                        title="Quality Score Distribution")

    citations = [p.get("citation_count") for p in included if p.get("citation_count")]
    if citations:
        figs["citations"] = px.histogram(x=citations, nbins=20,
                                          labels={"x": "Citation Count", "y": "Papers"},
                                          title="Citation Count Distribution")
    return figs


def _build_prisma_fig(all_papers: list[dict], counts: dict) -> go.Figure:
    by_source_oa = sum(1 for p in all_papers if p.get("source") == "openalex")
    by_source_ss = sum(1 for p in all_papers if p.get("source") == "semantic_scholar")
    by_snowball = sum(1 for p in all_papers if "snowball" in (p.get("found_via") or ""))
    excluded_count = sum(1 for p in all_papers if p.get("final_status") == "EXCLUDED")
    included_count = sum(1 for p in all_papers if p.get("final_status") == "INCLUDED")
    human_reviewed = sum(1 for p in all_papers if p.get("human_decision"))
    human_excluded = sum(1 for p in all_papers if p.get("human_decision") == "EXCLUDE")
    prisma = PRISMAData(
        identified_openalex=by_source_oa,
        identified_semantic_scholar=by_source_ss,
        identified_snowballing=by_snowball,
        duplicates_removed=0,
        screened_title_abstract=counts.get("total", 0),
        excluded_title_abstract=excluded_count,
        assessed_full_text=included_count + human_reviewed,
        excluded_full_text=human_excluded,
        human_reviewed=human_reviewed,
        human_excluded=human_excluded,
        included_final=included_count,
    )
    return build_prisma_figure(prisma)


def _papers_to_html_table(included: list[dict]) -> str:
    rows = []
    for p in included:
        try:
            authors = [a["name"] for a in (json.loads(p.get("authors") or "[]") or [])[:3]]
            author_str = "; ".join(authors)
        except Exception:
            author_str = ""
        rel = round(p.get("relevance_score") or 0, 1)
        rows.append({
            "Relevance": rel,
            "Title": p.get("title", ""),
            "Authors": author_str,
            "Year": p.get("year", ""),
            "Journal": (p.get("journal") or "")[:60],
            "Citations": p.get("citation_count") or 0,
            "Quality": round(p.get("quality_score") or 0, 1),
            "Cluster": p.get("cluster_label") or "",
            "DOI": p.get("doi") or "",
            "Abstract": (p.get("abstract") or "")[:300],
        })

    df = pd.DataFrame(rows).sort_values("Relevance", ascending=False)
    table_html = df.to_html(index=False, classes=["paper-table"], border=0, escape=True, na_rep="—")

    # Replace relevance number cells with a mini bar + number
    def _rel_cell(m):
        val = float(m.group(1))
        width = max(2, int(val * 0.8))
        return f'<td><span class="rel-bar" style="width:{width}px"></span> {val:.1f}</td>'

    table_html = re.sub(r'<td>(\d+\.?\d*)</td>(?=.*</tr>.*<td>', table_html, count=0)

    # Replace DOI plain text with clickable links
    table_html = re.sub(
        r'<td>(10\.[^\s<]+)</td>',
        r'<td><a href="https://doi.org/\1" target="_blank" rel="noopener">\1</a></td>',
        table_html,
    )
    return table_html


def _synthesis_to_html(synthesis: dict) -> str:
    def _mini_md(text: str) -> str:
        """Convert minimal markdown (bold, bullets) to HTML."""
        text = html.escape(text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        paragraphs = text.split('\n\n')
        parts = []
        for para in paragraphs:
            lines = para.strip().splitlines()
            if all(l.strip().startswith('- ') for l in lines if l.strip()):
                items = "".join(f"<li>{l.strip()[2:]}</li>" for l in lines if l.strip())
                parts.append(f"<ul>{items}</ul>")
            else:
                parts.append(f"<p>{para.replace(chr(10), '<br>')}</p>")
        return "\n".join(parts)

    def _list_section(title: str, items: list) -> str:
        if not items:
            return ""
        lis = "".join(f"<li>{html.escape(str(i))}</li>" for i in items)
        return f"<h3>{title}</h3><ul>{lis}</ul>"

    parts = []
    if synthesis.get("narrative_overview"):
        parts.append(f"<h3>Overview</h3>{_mini_md(synthesis['narrative_overview'])}")

    col_left = (
        _list_section("Key Themes", synthesis.get("key_themes") or [])
        + _list_section("Areas of Consensus", synthesis.get("consensus_points") or [])
    )
    col_right = (
        _list_section("Research Gaps", synthesis.get("research_gaps") or [])
        + _list_section("Key Debates", synthesis.get("key_debates") or [])
    )
    if col_left or col_right:
        parts.append(f'<div class="synth-cols"><div>{col_left}</div><div>{col_right}</div></div>')

    if synthesis.get("methodological_observations"):
        parts.append(f"<h3>Methodological Observations</h3>{_mini_md(synthesis['methodological_observations'])}")

    if synthesis.get("seminal_papers_notes"):
        parts.append(f"<h3>Seminal Papers</h3>{_mini_md(synthesis['seminal_papers_notes'])}")

    return "\n".join(parts) if parts else '<p class="placeholder">No synthesis content available.</p>'


def _embed_network(network_html: str | None) -> str:
    if not network_html:
        return '<div class="placeholder">Network diagram not included — run synthesis to generate embeddings first.</div>'
    escaped = html.escape(network_html, quote=True)
    return (
        f'<iframe srcdoc="{escaped}" '
        f'style="width:100%;height:700px;border:none;border-radius:6px;" '
        f'title="Paper Network"></iframe>'
    )


def _cluster_summaries_html(synthesis: dict) -> str:
    clusters = synthesis.get("cluster_summaries") or []
    if not clusters:
        return ""
    items = []
    for c in clusters:
        label = html.escape(str(c.get("label", "")))
        n = c.get("n_papers", "")
        summary = html.escape(str(c.get("summary", "")))
        items.append(f'<details class="cluster"><summary>{label} ({n} papers)</summary><div>{summary}</div></details>')
    return "<h3>Cluster Summaries</h3>" + "\n".join(items)


def _assemble(
    research_question: str,
    n_included: int,
    sections: dict[str, str],
    generated_at: str,
) -> str:
    rq_escaped = html.escape(research_question)
    toc_items = [
        ("papers", "Paper Table"),
        ("cluster-map", "Cluster Map"),
        ("statistics", "Publication Statistics"),
        ("synthesis", "Literature Synthesis"),
        ("prisma", "PRISMA Flow Diagram"),
        ("network", "Paper Network"),
    ]
    toc_html = "".join(f'<li><a href="#{sid}">{label}</a></li>' for sid, label in toc_items)

    cdn_script = f'<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>' if PLOTLYJS_STRATEGY == "cdn" else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Literature Review: {rq_escaped[:80]}</title>
  {cdn_script}
  <style>{_REPORT_CSS}</style>
</head>
<body>
<header>
  <h1>Literature Review Report</h1>
  <p class="meta">Generated: {generated_at} &nbsp;·&nbsp; Papers included: {n_included}</p>
  <p class="rq"><strong>Research question:</strong> {rq_escaped}</p>
</header>

<nav id="toc">
  <h2>Contents</h2>
  <ol>{toc_html}</ol>
</nav>

<section id="papers">
  <h2>📋 Included Papers</h2>
  {sections.get("papers", '<div class="placeholder">No papers available.</div>')}
</section>

<section id="cluster-map">
  <h2>🗺️ Topic Cluster Map</h2>
  {sections.get("cluster_map", '<div class="placeholder">Cluster map not available — run synthesis first.</div>')}
  {sections.get("cluster_summaries", "")}
</section>

<section id="statistics">
  <h2>📈 Publication Statistics</h2>
  <div class="chart-grid">
    {sections.get("stat_year", '<div class="placeholder">Year chart unavailable.</div>')}
    {sections.get("stat_journal", '<div class="placeholder">Journal chart unavailable.</div>')}
    {sections.get("stat_quality", '<div class="placeholder">Quality chart unavailable.</div>')}
    {sections.get("stat_citations", '<div class="placeholder">Citations chart unavailable.</div>')}
  </div>
</section>

<section id="synthesis">
  <h2>✍️ Literature Synthesis</h2>
  {sections.get("synthesis", '<div class="placeholder">Synthesis not available — run the full pipeline first.</div>')}
</section>

<section id="prisma">
  <h2>🔵 PRISMA 2020 Flow Diagram</h2>
  {sections.get("prisma", '<div class="placeholder">PRISMA diagram unavailable.</div>')}
</section>

<section id="network">
  <h2>🕸️ Paper Network</h2>
  {sections.get("network", '<div class="placeholder">Network diagram not included.</div>')}
</section>

<footer>
  <p>Generated by the Agentic Literature Review Tool &nbsp;·&nbsp; {generated_at}</p>
</footer>

<script>{_SORT_JS}</script>
</body>
</html>"""


def build_html_report(
    included: list[dict],
    all_papers: list[dict],
    synthesis: dict | None,
    counts: dict[str, int],
    research_question: str,
    network_html: str | None = None,
    embedding_map: dict | None = None,
) -> bytes:
    """
    Assemble a self-contained HTML dashboard report.
    Returns UTF-8 encoded bytes for st.download_button(data=...).
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections: dict[str, str] = {}
    plotlyjs_injected = False

    # Paper table
    try:
        sections["papers"] = _papers_to_html_table(included)
    except Exception as exc:
        sections["papers"] = f'<div class="placeholder">Paper table error: {html.escape(str(exc))}</div>'

    # Cluster map
    try:
        if synthesis:
            fig = _build_cluster_fig(included, synthesis)
            if fig:
                sections["cluster_map"] = _fig_to_div(fig, first=not plotlyjs_injected)
                plotlyjs_injected = True
                sections["cluster_summaries"] = _cluster_summaries_html(synthesis)
    except Exception as exc:
        sections["cluster_map"] = f'<div class="placeholder">Cluster map error: {html.escape(str(exc))}</div>'

    # Stats charts
    try:
        stat_figs = _build_stats_figs(included)
        for key, fig_key in [("year", "stat_year"), ("journal", "stat_journal"),
                              ("quality", "stat_quality"), ("citations", "stat_citations")]:
            fig = stat_figs.get(key)
            if fig:
                sections[fig_key] = _fig_to_div(fig, first=not plotlyjs_injected)
                plotlyjs_injected = True
    except Exception as exc:
        sections["stat_year"] = f'<div class="placeholder">Stats error: {html.escape(str(exc))}</div>'

    # Synthesis text
    try:
        if synthesis:
            sections["synthesis"] = _synthesis_to_html(synthesis)
    except Exception as exc:
        sections["synthesis"] = f'<div class="placeholder">Synthesis error: {html.escape(str(exc))}</div>'

    # PRISMA
    try:
        fig_prisma = _build_prisma_fig(all_papers, counts)
        sections["prisma"] = _fig_to_div(fig_prisma, first=not plotlyjs_injected)
        plotlyjs_injected = True
    except Exception as exc:
        sections["prisma"] = f'<div class="placeholder">PRISMA error: {html.escape(str(exc))}</div>'

    # Network
    try:
        sections["network"] = _embed_network(network_html)
    except Exception as exc:
        sections["network"] = f'<div class="placeholder">Network error: {html.escape(str(exc))}</div>'

    html_str = _assemble(research_question, len(included), sections, generated_at)
    return html_str.encode("utf-8")
