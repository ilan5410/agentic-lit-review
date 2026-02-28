"""Page 3: Results Dashboard — paper table, cluster map, statistics, synthesis, network."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Results", page_icon="📊", layout="wide")

if "pipeline_stage" not in st.session_state:
    st.switch_page("app.py")

from data.database import get_papers, get_synthesis, count_papers, get_embeddings
from utils.prisma import PRISMAData, build_prisma_figure

conn = st.session_state.get("db_conn")
if not conn:
    st.error("No database connection.")
    st.stop()

counts = count_papers(conn)
if counts["total"] == 0:
    st.warning("No papers yet. Run the pipeline first.")
    st.stop()

# ── Load data ──────────────────────────────────────────────────────────────────
all_papers = get_papers(conn)
included = [p for p in all_papers if p.get("final_status") == "INCLUDED"]
synthesis = get_synthesis(conn)

# ── Header ─────────────────────────────────────────────────────────────────────
col_title, col_rescore = st.columns([5, 1])
with col_title:
    st.title("📊 Results Dashboard")
    st.caption(
        f"**{counts['included']}** papers included from **{counts['total']}** retrieved | "
        f"Stage: {st.session_state.get('pipeline_stage', '?')}"
    )
with col_rescore:
    st.write("")
    st.write("")
    has_scores = any(p.get("relevance_score") for p in included)
    btn_label = "🔄 Re-score Relevance" if has_scores else "⚡ Score Relevance"
    if st.button(btn_label, help="Score all included papers by semantic similarity to the research question"):
        from agents.orchestrator import Orchestrator
        log_placeholder = st.empty()
        def _cb(msg): log_placeholder.info(msg)
        orch = Orchestrator(conn, st.session_state, _cb)
        orch.run_relevance_scoring()
        log_placeholder.success("Relevance scoring complete!")
        st.rerun()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["📋 Paper Table", "🗺️ Cluster Map", "📈 Statistics", "✍️ Synthesis", "🔵 PRISMA", "🕸️ Network"]
)


# ── Tab 1: Paper Table ─────────────────────────────────────────────────────────
with tab1:
    if not included:
        st.info("No included papers yet.")
    else:
        st.subheader(f"Included Papers ({len(included)})")

        # Build display dataframe
        rows = []
        for p in included:
            authors = []
            try:
                authors = [a["name"] for a in (json.loads(p.get("authors") or "[]") or [])[:3]]
            except Exception:
                pass
            rows.append({
                "Relevance": round(p.get("relevance_score") or 0, 1),
                "Title": p.get("title", ""),
                "Authors": "; ".join(authors),
                "Year": p.get("year"),
                "Journal": p.get("journal", ""),
                "Citations": p.get("citation_count", 0),
                "Quality": round(p.get("quality_score") or 0, 1),
                "Cluster": p.get("cluster_label", ""),
                "DOI": p.get("doi", ""),
                "OA": "🔓" if p.get("open_access_url") else "",
            })

        df = pd.DataFrame(rows).sort_values("Relevance", ascending=False)

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            year_filter = st.multiselect(
                "Filter by year",
                options=sorted(df["Year"].dropna().unique().tolist(), reverse=True),
                default=[],
            )
        with col2:
            cluster_filter = st.multiselect(
                "Filter by cluster",
                options=sorted(df["Cluster"].dropna().unique().tolist()),
                default=[],
            )
        with col3:
            search_text = st.text_input("Search title / authors", "")

        filtered = df.copy()
        if year_filter:
            filtered = filtered[filtered["Year"].isin(year_filter)]
        if cluster_filter:
            filtered = filtered[filtered["Cluster"].isin(cluster_filter)]
        if search_text:
            mask = (
                filtered["Title"].str.contains(search_text, case=False, na=False)
                | filtered["Authors"].str.contains(search_text, case=False, na=False)
            )
            filtered = filtered[mask]

        st.dataframe(
            filtered,
            use_container_width=True,
            height=480,
            column_config={
                "Relevance": st.column_config.ProgressColumn(
                    "Relevance", min_value=0, max_value=100, format="%.1f",
                    help="Semantic similarity to research question (0–100)",
                ),
                "Title": st.column_config.TextColumn(width="large"),
                "Citations": st.column_config.NumberColumn(format="%d"),
                "Quality": st.column_config.NumberColumn(format="%.1f"),
                "DOI": st.column_config.LinkColumn(display_text="DOI"),
            },
        )
        st.caption(f"Showing {len(filtered)} of {len(included)} papers")

        # Detail expanders
        with st.expander("Show paper details (click to expand)"):
            paper_idx = st.selectbox("Select paper", options=range(len(included)), format_func=lambda i: included[i].get("title", "")[:80])
            p = included[paper_idx]
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{p.get('title')}**")
                try:
                    authors = [a["name"] for a in json.loads(p.get("authors") or "[]")]
                    st.caption(", ".join(authors[:5]))
                except Exception:
                    pass
                if p.get("abstract"):
                    st.markdown(p["abstract"])
            with col2:
                st.metric("Year", p.get("year", "?"))
                st.metric("Citations", p.get("citation_count", 0))
                st.metric("Quality", round(p.get("quality_score") or 0, 1))
                if p.get("relevance_score") is not None:
                    st.metric("Relevance", f"{p['relevance_score']:.1f} / 100")
                if p.get("doi"):
                    st.markdown(f"[View →](https://doi.org/{p['doi']})")
                if p.get("open_access_url"):
                    st.markdown(f"[PDF →]({p['open_access_url']})")
                if p.get("quality_notes"):
                    st.caption(f"Quality notes: {p['quality_notes']}")

# ── Tab 2: Cluster Map ─────────────────────────────────────────────────────────
with tab2:
    if not synthesis or not synthesis.get("coords_2d"):
        st.info("Cluster map available after synthesis is complete.")
    else:
        st.subheader("Topic Cluster Map")
        coords = synthesis.get("coords_2d", [])
        paper_ids = synthesis.get("paper_ids", [])

        # Build lookup
        id_to_paper = {p["id"]: p for p in included}

        plot_data = []
        for pid, (x, y) in zip(paper_ids, coords):
            p = id_to_paper.get(pid, {})
            try:
                authors = [a["name"] for a in json.loads(p.get("authors") or "[]")]
                author_str = ", ".join(authors[:2])
            except Exception:
                author_str = ""
            plot_data.append({
                "x": x, "y": y,
                "title": p.get("title", "?"),
                "cluster": p.get("cluster_label", "Uncategorised"),
                "year": p.get("year", ""),
                "citations": p.get("citation_count", 0),
                "author": author_str,
            })

        plot_df = pd.DataFrame(plot_data)
        fig = px.scatter(
            plot_df,
            x="x", y="y",
            color="cluster",
            hover_data={"title": True, "author": True, "year": True, "citations": True, "x": False, "y": False},
            title="Paper clusters (2D projection of semantic embeddings)",
            labels={"x": "Dimension 1", "y": "Dimension 2"},
        )
        fig.update_traces(marker=dict(size=10, opacity=0.8))
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            legend_title="Cluster",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Cluster legend
        clusters = synthesis.get("cluster_summaries", [])
        if clusters:
            st.subheader("Cluster Summaries")
            for c in clusters:
                with st.expander(f"**{c['label']}** ({c['n_papers']} papers)"):
                    st.write(c.get("summary", ""))

# ── Tab 3: Statistics ──────────────────────────────────────────────────────────
with tab3:
    st.subheader("Publication Statistics")

    if not included:
        st.info("No included papers yet.")
    else:
        col1, col2 = st.columns(2)

        # Papers by year
        year_counts = pd.Series([p.get("year") for p in included if p.get("year")]).value_counts().sort_index()
        with col1:
            fig_year = px.bar(
                x=year_counts.index.tolist(),
                y=year_counts.values.tolist(),
                labels={"x": "Year", "y": "Papers"},
                title="Papers by Year",
            )
            fig_year.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_year, use_container_width=True)

        # Papers by journal
        journal_counts = (
            pd.Series([p.get("journal") for p in included if p.get("journal")])
            .value_counts()
            .head(15)
        )
        with col2:
            if not journal_counts.empty:
                fig_journal = px.bar(
                    x=journal_counts.values.tolist(),
                    y=journal_counts.index.tolist(),
                    orientation="h",
                    labels={"x": "Papers", "y": "Journal"},
                    title="Top Journals",
                )
                fig_journal.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_journal, use_container_width=True)

        col3, col4 = st.columns(2)

        # Quality distribution
        quality_scores = [p.get("quality_score") for p in included if p.get("quality_score")]
        with col3:
            if quality_scores:
                fig_q = px.histogram(
                    x=quality_scores,
                    nbins=20,
                    labels={"x": "Quality Score", "y": "Count"},
                    title="Quality Score Distribution",
                )
                fig_q.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_q, use_container_width=True)

        # Citation distribution
        citations = [p.get("citation_count") for p in included if p.get("citation_count")]
        with col4:
            if citations:
                fig_c = px.histogram(
                    x=citations,
                    nbins=20,
                    labels={"x": "Citation Count", "y": "Papers"},
                    title="Citation Count Distribution",
                )
                fig_c.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_c, use_container_width=True)


# ── Tab 4: Synthesis ───────────────────────────────────────────────────────────
with tab4:
    if not synthesis:
        st.info("Synthesis is generated at the end of the pipeline.")
    else:
        st.subheader("AI-Generated Literature Synthesis")

        if synthesis.get("narrative_overview"):
            st.markdown("### Overview")
            st.markdown(synthesis["narrative_overview"])

        col1, col2 = st.columns(2)
        with col1:
            if synthesis.get("key_themes"):
                st.markdown("### Key Themes")
                for t in synthesis["key_themes"]:
                    st.markdown(f"- {t}")

            if synthesis.get("consensus_points"):
                st.markdown("### Areas of Consensus")
                for c in synthesis["consensus_points"]:
                    st.markdown(f"- {c}")

        with col2:
            if synthesis.get("research_gaps"):
                st.markdown("### Research Gaps")
                for g in synthesis["research_gaps"]:
                    st.markdown(f"- {g}")

            if synthesis.get("key_debates"):
                st.markdown("### Key Debates")
                for d in synthesis["key_debates"]:
                    st.markdown(f"- {d}")

        if synthesis.get("methodological_observations"):
            st.markdown("### Methodological Observations")
            st.markdown(synthesis["methodological_observations"])

        if synthesis.get("seminal_papers_notes"):
            st.markdown("### Seminal Papers")
            st.markdown(synthesis["seminal_papers_notes"])


# ── Tab 5: PRISMA ──────────────────────────────────────────────────────────────
with tab5:
    st.subheader("PRISMA 2020 Flow Diagram")

    # Calculate PRISMA data from pipeline counts
    all_p = get_papers(conn)
    by_source_oa = sum(1 for p in all_p if p.get("source") == "openalex")
    by_source_ss = sum(1 for p in all_p if p.get("source") == "semantic_scholar")
    by_snowball = sum(1 for p in all_p if "snowball" in (p.get("found_via") or ""))

    excluded_count = sum(1 for p in all_p if p.get("final_status") == "EXCLUDED")
    included_count = sum(1 for p in all_p if p.get("final_status") == "INCLUDED")
    human_reviewed = sum(1 for p in all_p if p.get("human_decision"))
    human_excluded = sum(1 for p in all_p if p.get("human_decision") == "EXCLUDE")

    prisma = PRISMAData(
        identified_openalex=by_source_oa,
        identified_semantic_scholar=by_source_ss,
        identified_snowballing=by_snowball,
        duplicates_removed=0,  # tracked at insertion time
        screened_title_abstract=counts["total"],
        excluded_title_abstract=excluded_count,
        assessed_full_text=included_count + human_reviewed,
        excluded_full_text=human_excluded,
        human_reviewed=human_reviewed,
        human_excluded=human_excluded,
        included_final=included_count,
    )

    fig_prisma = build_prisma_figure(prisma)
    st.plotly_chart(fig_prisma, use_container_width=True)


# ── Tab 6: Paper Network ───────────────────────────────────────────────────────
with tab6:
    st.subheader("Paper Network")

    if not included:
        st.info("No included papers yet.")
    else:
        from utils.network import build_network

        col_nw1, col_nw2, col_nw3, col_nw4 = st.columns(4)
        with col_nw1:
            network_type = st.radio(
                "Network type",
                options=["citation", "similarity"],
                format_func=lambda x: "Citation graph" if x == "citation" else "Semantic similarity",
                horizontal=True,
            )
        with col_nw2:
            max_nodes = st.slider("Max papers shown", min_value=20, max_value=200, value=120, step=10)
        with col_nw3:
            if network_type == "similarity":
                sim_k = st.slider("Neighbours per paper (k)", min_value=2, max_value=10, value=4)
                sim_thresh = st.slider("Min similarity", min_value=0.3, max_value=0.9, value=0.55, step=0.05)
            else:
                sim_k, sim_thresh = 4, 0.55
        with col_nw4:
            top_n = st.slider("Key papers to highlight", min_value=3, max_value=20, value=10,
                              help="Top N papers by network centrality, highlighted in red")

        # Build embedding map for similarity network
        embedding_map = None
        if network_type == "similarity":
            stored = get_embeddings(conn)
            if stored:
                embedding_map = {pid: vec for pid, vec in stored}
            else:
                st.warning("No embeddings found. Run synthesis first to enable semantic similarity network.")

        with st.spinner("Building network…"):
            html_str, n_nodes, n_edges, important_papers = build_network(
                included,
                network_type=network_type,
                max_nodes=max_nodes,
                similarity_k=sim_k,
                similarity_threshold=sim_thresh,
                embedding_map=embedding_map,
                top_n=top_n,
            )

        st.caption(f"Showing **{n_nodes}** papers · **{n_edges}** edges")

        if network_type == "citation" and n_edges < 5:
            st.warning(
                "Very few citation edges found. This often means the papers don't cite each other within this corpus. "
                "Try the **Semantic similarity** network instead."
            )

        components.html(html_str, height=700, scrolling=False)

        # ── Key papers list ────────────────────────────────────────────────────
        if important_papers:
            metric_label = "times cited within corpus" if network_type == "citation" else "similar neighbours"
            st.markdown("---")
            st.markdown(f"### ⭐ Key Papers — Top {len(important_papers)} by network centrality")
            st.caption(
                "Ranked by **in-degree** (how many other papers in this corpus cite them)"
                if network_type == "citation"
                else "Ranked by **degree** (how many similar papers they are connected to)"
            )

            for rank, p in enumerate(important_papers, start=1):
                try:
                    authors = [a["name"] for a in json.loads(p.get("authors") or "[]")][:3]
                    author_str = "; ".join(authors) or "Unknown"
                except Exception:
                    author_str = "Unknown"

                with st.container():
                    c1, c2 = st.columns([6, 1])
                    with c1:
                        title_md = p.get("title") or "Untitled"
                        doi = p.get("doi")
                        title_link = f"[{title_md}](https://doi.org/{doi})" if doi else f"**{title_md}**"
                        st.markdown(f"**#{rank}** {title_link}")
                        st.caption(
                            f"{author_str} · {p.get('year', '?')} · "
                            f"Cluster: {p.get('cluster_label') or 'Uncategorised'} · "
                            f"Relevance: {p.get('relevance_score') or 0:.1f}/100"
                        )
                    with c2:
                        st.metric(metric_label, p["_connections"])
        else:
            st.info("No network connections found — key papers cannot be determined. Try adjusting the settings above.")
