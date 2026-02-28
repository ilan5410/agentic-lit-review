"""Page 2: Review Progress — live pipeline execution, error display, and HITL queue."""
from __future__ import annotations

import traceback
import json

import streamlit as st

st.set_page_config(page_title="Review Progress", page_icon="🔄", layout="wide")

if "pipeline_stage" not in st.session_state:
    st.switch_page("app.py")

from data.database import get_log, count_papers, get_papers, update_paper
from agents.orchestrator import Orchestrator

# ── Stage progress bar ─────────────────────────────────────────────────────────

ORDERED_STAGES = [
    ("RUNNING_QUERY",    "Query"),
    ("QUERY_APPROVAL",   "Approve queries"),
    ("RUNNING_SEARCH",   "Search"),
    ("RUNNING_SCREENING","Screen"),
    ("HITL_REVIEW",      "Your review"),
    ("RUNNING_SNOWBALL", "Snowball"),
    ("RUNNING_QUALITY",  "Quality"),
    ("RUNNING_SYNTHESIS","Synthesis"),
    ("COMPLETE",         "Done"),
]

def _stage_bar(current: str) -> None:
    stage_keys = [s[0] for s in ORDERED_STAGES]
    labels     = [s[1] for s in ORDERED_STAGES]
    try:
        idx = stage_keys.index(current)
    except ValueError:
        idx = 0
    cols = st.columns(len(ORDERED_STAGES))
    for i, (col, label) in enumerate(zip(cols, labels)):
        if i < idx:
            col.markdown(f"<div style='text-align:center;color:#22c55e;font-size:11px'>✓ {label}</div>", unsafe_allow_html=True)
        elif i == idx:
            col.markdown(f"<div style='text-align:center;color:#3b82f6;font-weight:bold;font-size:11px'>▶ {label}</div>", unsafe_allow_html=True)
        else:
            col.markdown(f"<div style='text-align:center;color:#475569;font-size:11px'>{label}</div>", unsafe_allow_html=True)
    st.progress((idx) / (len(ORDERED_STAGES) - 1))


# ── Live-log callback ──────────────────────────────────────────────────────────

def _make_callback(log_placeholder):
    """Returns a callback that writes each message into the placeholder."""
    messages: list[str] = []

    def cb(msg: str) -> None:
        messages.append(msg)
        # Keep last 30 lines; update the placeholder in real-time
        log_placeholder.markdown(
            "\n\n".join(f"`{m}`" for m in messages[-30:]),
            unsafe_allow_html=False,
        )

    return cb


def _show_db_log(conn) -> None:
    with st.expander("Activity log", expanded=False):
        entries = get_log(conn, limit=100)
        if entries:
            for e in reversed(entries):
                st.caption(f"[{e['stage']}] {e['message']}")
        else:
            st.caption("No log entries yet.")


def _error(label: str, exc: Exception) -> None:
    st.error(f"**{label}**: {exc}")
    with st.expander("Full traceback"):
        st.code(traceback.format_exc())
    if st.button("Reset to beginning"):
        st.session_state.pipeline_stage = "IDLE"
        st.rerun()


# ── Main ───────────────────────────────────────────────────────────────────────

st.title("🔄 Review Progress")

conn   = st.session_state.get("db_conn")
cfg    = st.session_state.get("review_config", {})
stage  = st.session_state.get("pipeline_stage", "IDLE")

if not conn:
    st.error("No database connection. Return to the home page.")
    st.stop()

if not cfg.get("research_question"):
    st.warning("No review configured. Go to **Define Review** first.")
    if st.button("Go to Define Review"):
        st.switch_page("pages/1_📋_Define_Review.py")
    st.stop()

_stage_bar(stage)
st.caption(f"Research question: _{cfg.get('research_question', '')[:120]}_")
st.divider()

# ── IDLE ───────────────────────────────────────────────────────────────────────
if stage == "IDLE":
    st.info("Pipeline is ready. Click a button below to start.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Generate Search Strategy Only", type="secondary", use_container_width=True):
            st.session_state.run_query_only = True
            st.session_state.pipeline_stage = "RUNNING_QUERY"
            st.rerun()
    with col2:
        if st.button("🚀 Launch Full Pipeline", type="primary", use_container_width=True):
            st.session_state.run_query_only = False
            st.session_state.pipeline_stage = "RUNNING_QUERY"
            st.rerun()
    st.stop()

# ── RUNNING_QUERY ──────────────────────────────────────────────────────────────
if stage == "RUNNING_QUERY":
    log_ph = st.empty()
    with st.status("Query Agent: formulating search strategy…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            queries = orch.run_query_formulation()
            status.update(label="Search strategy ready!", state="complete")
        except Exception as exc:
            status.update(label="Query formulation failed", state="error")
            _error("Query Agent failed", exc)
            st.stop()

    st.session_state.generated_queries = queries
    st.session_state.pipeline_stage = "QUERY_APPROVAL"
    st.rerun()

# ── QUERY_APPROVAL ─────────────────────────────────────────────────────────────
if stage == "QUERY_APPROVAL":
    queries = st.session_state.get("generated_queries", {})
    st.subheader("Generated Search Queries — review before running")

    if queries.get("notes_for_user"):
        st.info(queries["notes_for_user"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**OpenAlex queries**")
        for q in queries.get("openalex_queries", []):
            st.code(q["query"], language="text")
            if q.get("description"):
                st.caption(q["description"])
    with col2:
        st.markdown("**Semantic Scholar queries**")
        for q in queries.get("semantic_scholar_queries", []):
            st.code(q["query"], language="text")
            if q.get("description"):
                st.caption(q["description"])

    if queries.get("suggested_concepts"):
        st.caption(f"Suggested concepts: {', '.join(queries['suggested_concepts'])}")

    st.divider()
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        if st.button("✅ Approve & Run Search", type="primary", use_container_width=True,
                     disabled=st.session_state.get("run_query_only", False)):
            st.session_state.pipeline_stage = "RUNNING_SEARCH"
            st.rerun()
    with col2:
        if st.button("🔄 Regenerate queries", use_container_width=True):
            st.session_state.pipeline_stage = "RUNNING_QUERY"
            st.rerun()
    with col3:
        if st.button("← Back", use_container_width=True):
            st.switch_page("pages/1_📋_Define_Review.py")

    if st.session_state.get("run_query_only"):
        st.info("Query-only mode. Approve to run the full search.")
    st.stop()

# ── RUNNING_SEARCH ─────────────────────────────────────────────────────────────
if stage == "RUNNING_SEARCH":
    log_ph = st.empty()
    with st.status("Search Agent: querying databases…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            total = orch.run_search()
            status.update(label=f"Search complete — {total} unique papers found.", state="complete")
        except Exception as exc:
            status.update(label="Search failed", state="error")
            _error("Search Agent failed", exc)
            st.stop()

    counts = count_papers(conn)
    st.metric("Papers retrieved", counts["total"])
    st.session_state.pipeline_stage = "RUNNING_SCREENING"
    st.rerun()

# ── RUNNING_SCREENING ──────────────────────────────────────────────────────────
if stage == "RUNNING_SCREENING":
    log_ph = st.empty()
    with st.status("Screening Agent: title + abstract screening…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            screen_counts = orch.run_screening_pass1()
            status.update(
                label=(
                    f"Screening complete — Include: {screen_counts['include']}, "
                    f"Exclude: {screen_counts['exclude']}, "
                    f"Borderline: {screen_counts['borderline']}"
                ),
                state="complete",
            )
        except Exception as exc:
            status.update(label="Screening failed", state="error")
            _error("Screening Agent failed", exc)
            st.stop()

    col1, col2, col3 = st.columns(3)
    col1.metric("Include", screen_counts["include"])
    col2.metric("Exclude", screen_counts["exclude"])
    col3.metric("Borderline", screen_counts["borderline"])

    # Decide next stage
    borderline_count = screen_counts.get("borderline", 0)
    if cfg.get("hitl_enabled", True) and borderline_count > 0:
        st.session_state.pipeline_stage = "HITL_REVIEW"
    elif cfg.get("enable_snowballing", True):
        st.session_state.pipeline_stage = "RUNNING_SNOWBALL"
    else:
        st.session_state.pipeline_stage = "RUNNING_QUALITY"
    st.rerun()

# ── HITL_REVIEW ────────────────────────────────────────────────────────────────
if stage == "HITL_REVIEW":
    st.subheader("Your review — borderline papers")
    st.info(
        "The screening agent flagged these papers as uncertain. "
        "Mark each **Include** or **Exclude**, then click **Continue Pipeline**."
    )

    borderline = [
        p for p in get_papers(conn)
        if p.get("screening_pass1") == "BORDERLINE" and not p.get("human_decision")
    ]
    decided = [
        p for p in get_papers(conn)
        if p.get("screening_pass1") == "BORDERLINE" and p.get("human_decision")
    ]

    if borderline:
        st.write(f"**{len(borderline)} remaining** · {len(decided)} decided")
        for p in borderline:
            authors = []
            try:
                authors = [a["name"] for a in (json.loads(p.get("authors") or "[]") or [])[:3]]
            except Exception:
                pass
            with st.expander(
                f"📄 {p.get('title', 'Untitled')} ({p.get('year', '?')}) — {', '.join(authors[:2])}"
            ):
                st.caption(f"**Journal:** {p.get('journal', '—')} · **Citations:** {p.get('citation_count', 0)}")
                st.caption(f"**Agent reasoning:** _{p.get('screening_pass1_reason', '—')}_")
                if p.get("abstract"):
                    abs_text = p["abstract"]
                    st.markdown(abs_text[:600] + ("…" if len(abs_text) > 600 else ""))
                if p.get("doi"):
                    st.markdown(f"[View paper →](https://doi.org/{p['doi']})")
                bcol1, bcol2 = st.columns(2)
                with bcol1:
                    if st.button("✅ Include", key=f"inc_{p['id']}", use_container_width=True):
                        update_paper(conn, p["id"], human_decision="INCLUDE")
                        st.rerun()
                with bcol2:
                    if st.button("❌ Exclude", key=f"exc_{p['id']}", use_container_width=True):
                        update_paper(conn, p["id"], human_decision="EXCLUDE")
                        st.rerun()
    else:
        st.success(f"All {len(decided)} borderline papers reviewed.")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Continue Pipeline", type="primary", use_container_width=True):
            log_ph = st.empty()
            with st.status("Applying your decisions…", expanded=True) as status:
                orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
                orch.resume_after_hitl()
                status.update(label="Decisions applied.", state="complete")
            next_stage = "RUNNING_SNOWBALL" if cfg.get("enable_snowballing", True) else "RUNNING_QUALITY"
            st.session_state.pipeline_stage = next_stage
            st.rerun()
    with col2:
        st.caption("Your decisions are saved automatically. You can come back later.")
    st.stop()

# ── RUNNING_SNOWBALL ───────────────────────────────────────────────────────────
if stage == "RUNNING_SNOWBALL":
    log_ph = st.empty()
    with st.status("Snowballing Agent: expanding citation network…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            n_new = orch.run_snowballing()
            status.update(label=f"Snowballing complete — {n_new} new papers added.", state="complete")
        except Exception as exc:
            status.update(label="Snowballing failed", state="error")
            _error("Snowballing Agent failed", exc)
            st.stop()

    st.metric("New papers found via snowballing", n_new)
    st.session_state.pipeline_stage = "RUNNING_QUALITY"
    st.rerun()

# ── RUNNING_QUALITY ────────────────────────────────────────────────────────────
if stage == "RUNNING_QUALITY":
    included_count = count_papers(conn)["included"]
    log_ph = st.empty()
    with st.status(f"Quality Agent: assessing {included_count} included papers…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            orch.run_quality_assessment()
            status.update(label="Quality assessment complete.", state="complete")
        except Exception as exc:
            status.update(label="Quality assessment failed", state="error")
            _error("Quality Agent failed", exc)
            st.stop()

    st.session_state.pipeline_stage = "RUNNING_SYNTHESIS"
    st.rerun()

# ── RUNNING_SYNTHESIS ──────────────────────────────────────────────────────────
if stage == "RUNNING_SYNTHESIS":
    included_count = count_papers(conn)["included"]
    log_ph = st.empty()
    with st.status(f"Synthesis Agent: clustering and synthesising {included_count} papers…", expanded=True) as status:
        try:
            orch = Orchestrator(conn, st.session_state, _make_callback(log_ph))
            result = orch.run_synthesis()
            st.session_state.pipeline_stage = "COMPLETE"
            status.update(label="Synthesis complete.", state="complete")
        except Exception as exc:
            status.update(label="Synthesis failed", state="error")
            _error("Synthesis Agent failed", exc)
            st.stop()

    st.rerun()

# ── COMPLETE ───────────────────────────────────────────────────────────────────
if stage == "COMPLETE":
    st.success("Pipeline complete!")
    counts = count_papers(conn)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total retrieved", counts["total"])
    col2.metric("Included", counts["included"])
    col3.metric("Excluded", counts["excluded"])
    col4.metric("Borderline (pending)", counts["borderline"])

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 View Results", type="primary", use_container_width=True):
            st.switch_page("pages/3_📊_Results.py")
    with col2:
        if st.button("📥 Download Exports", use_container_width=True):
            st.switch_page("pages/4_📥_Export.py")

    _show_db_log(conn)
