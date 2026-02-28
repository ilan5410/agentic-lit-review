"""
Agentic Literature Review Tool — Main Streamlit entry point.
"""
import uuid
import streamlit as st

from data.database import get_db_path, get_connection

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lit Review Agent",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialisation ───────────────────────────────────────────────
def _init_state() -> None:
    defaults = {
        "session_id": str(uuid.uuid4())[:8],
        "pipeline_stage": "IDLE",
        "review_config": {},
        "generated_queries": {},
        "pipeline_log": [],
        "openai_api_key": "",
        "db_conn": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ── Ensure DB connection ────────────────────────────────────────────────────────
if st.session_state.db_conn is None:
    db_path = get_db_path(st.session_state.session_id)
    st.session_state.db_conn = get_connection(db_path)

# ── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📚 Lit Review Agent")
    st.caption("Agentic systematic literature review")
    st.divider()

    st.subheader("🔑 API Keys")
    api_key = st.text_input(
        "OpenAI API Key",
        value=st.session_state.openai_api_key,
        type="password",
        placeholder="sk-...",
        help="Required. Your OpenAI key — never stored on server.",
    )
    if api_key:
        st.session_state.openai_api_key = api_key

    st.divider()
    st.subheader("📊 Session Status")
    stage = st.session_state.pipeline_stage
    stage_icons = {
        "IDLE": "⏳ Ready",
        "QUERY_FORMULATION": "🔍 Formulating queries",
        "QUERY_APPROVAL": "✋ Awaiting approval",
        "SEARCHING": "🌐 Searching databases",
        "DEDUPLICATION": "🔄 Deduplicating",
        "SCREENING_PASS_1": "📋 Screening papers",
        "HITL_REVIEW": "👤 Awaiting your review",
        "SNOWBALLING": "❄️ Snowballing",
        "QUALITY_ASSESSMENT": "⭐ Quality assessment",
        "SYNTHESIS": "✍️ Synthesising",
        "COMPLETE": "✅ Complete",
    }
    st.info(stage_icons.get(stage, stage))

    if st.session_state.db_conn:
        try:
            from data.database import count_papers
            counts = count_papers(st.session_state.db_conn)
            col1, col2 = st.columns(2)
            col1.metric("Total", counts["total"])
            col2.metric("Included", counts["included"])
            col1.metric("Excluded", counts["excluded"])
            col2.metric("Borderline", counts["borderline"])
        except Exception:
            pass

    st.divider()
    if st.button("🔄 Start New Review", use_container_width=True):
        # Reset session
        import os, tempfile
        old_path = get_db_path(st.session_state.session_id)
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        _init_state()
        db_path = get_db_path(st.session_state.session_id)
        st.session_state.db_conn = get_connection(db_path)
        st.rerun()

    st.caption(f"Session: {st.session_state.session_id}")

# ── Home page content ───────────────────────────────────────────────────────────
st.title("📚 Agentic Literature Review Tool")

st.markdown("""
Welcome! This tool runs a **multi-agent pipeline** to conduct a systematic literature review:

| Step | Agent | What it does |
|------|-------|-------------|
| 1 | **Query Agent** | Converts your research question into optimised database search queries |
| 2 | **Search Agent** | Searches OpenAlex (271M papers) + Semantic Scholar (200M papers) |
| 3 | **Screening Agent** | Screens papers on title/abstract against your inclusion criteria |
| 4 | **You** | Review borderline papers (if HITL enabled) |
| 5 | **Snowballing Agent** | Follows citation networks to find missed papers |
| 6 | **Quality Agent** | Assesses methodological quality of included papers |
| 7 | **Synthesis Agent** | Clusters papers, generates narrative synthesis + gap analysis |

### Getting started

1. Enter your **OpenAI API key** in the sidebar
2. Go to **Define Review** to describe your research question
3. Launch the pipeline and monitor progress on the **Progress** page
4. Explore results on the **Results** page and download exports from **Export**
""")

if not st.session_state.openai_api_key:
    st.warning("Enter your OpenAI API key in the sidebar to get started.")
else:
    st.success("API key set. Navigate to **Define Review** to begin.")

st.divider()
st.caption(
    "Data sources: [OpenAlex](https://openalex.org) · [Semantic Scholar](https://www.semanticscholar.org) · "
    "Powered by OpenAI GPT-4o"
)
