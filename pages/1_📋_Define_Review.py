"""Page 1: Define Review — research question, constraints, and screening configuration."""
import streamlit as st

st.set_page_config(page_title="Define Review", page_icon="📋", layout="wide")

# Guard: session state must be initialised from app.py
if "pipeline_stage" not in st.session_state:
    st.switch_page("app.py")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _save_config(cfg: dict) -> None:
    from data.database import save_config
    st.session_state.review_config = cfg
    if st.session_state.get("db_conn"):
        save_config(st.session_state.db_conn, cfg)


def _launch(cfg: dict, query_only: bool = False) -> None:
    if not st.session_state.get("openai_api_key"):
        st.error("Enter your OpenAI API key in the sidebar first.")
        return
    _save_config(cfg)
    st.session_state.pipeline_stage = "RUNNING_QUERY"
    st.session_state["run_query_only"] = bool(query_only)
    st.switch_page("pages/2_🔄_Progress.py")


# ── UI ─────────────────────────────────────────────────────────────────────────
st.title("📋 Define Your Literature Review")

# Pre-fill from existing config if returning
existing = st.session_state.get("review_config", {})

# ── 1.1 Research Question ──────────────────────────────────────────────────────
st.subheader("1. Research Question")
research_question = st.text_area(
    "Describe your research topic or question",
    value=existing.get("research_question", ""),
    height=120,
    placeholder=(
        "e.g. 'What is the effect of mindfulness-based interventions on anxiety "
        "in adults with chronic illness? Focus on RCTs published 2015–2024.'"
    ),
    help="Be as specific or broad as you like — the Query Agent will refine the search strategy.",
)

# ── 1.2 Structured Constraints ────────────────────────────────────────────────
with st.expander("2. Structured Constraints (optional)", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        keywords = st.text_input(
            "Include keywords (comma-separated)",
            value=existing.get("keywords", ""),
            placeholder="mindfulness, CBT, anxiety",
        )
        year_range = st.slider(
            "Publication year range",
            min_value=1950,
            max_value=2026,
            value=(existing.get("year_min", 2000), existing.get("year_max", 2026)),
        )
        disciplines = st.multiselect(
            "Disciplines / fields",
            options=[
                "Medicine", "Psychology", "Neuroscience", "Computer Science",
                "Biology", "Chemistry", "Physics", "Engineering", "Economics",
                "Education", "Sociology", "Environmental Science", "Other",
            ],
            default=existing.get("disciplines", []),
        )
        min_citations = st.number_input(
            "Minimum citation count",
            min_value=0,
            value=existing.get("min_citations", 0),
        )

    with col2:
        exclude_keywords = st.text_input(
            "Exclude keywords (comma-separated)",
            value=existing.get("exclude_keywords", ""),
            placeholder="animal study, pediatric",
        )
        document_types = st.multiselect(
            "Document types",
            options=["article", "review", "conference-paper", "preprint", "book-chapter"],
            default=existing.get("document_types", ["article", "review"]),
        )
        language = st.selectbox(
            "Language",
            options=["Any", "English", "French", "German", "Spanish", "Other"],
            index=["Any", "English", "French", "German", "Spanish", "Other"].index(
                existing.get("language", "Any")
            ),
        )
        oa_only = st.checkbox(
            "Open access only",
            value=existing.get("oa_only", False),
        )

# ── 1.3 Screening Configuration ───────────────────────────────────────────────
st.subheader("3. Screening Configuration")

col_a, col_b = st.columns(2)
with col_a:
    review_type = st.radio(
        "Review type",
        options=["Systematic review", "Scoping review", "Rapid evidence assessment", "Narrative review"],
        index=["Systematic review", "Scoping review", "Rapid evidence assessment", "Narrative review"].index(
            existing.get("review_type", "Systematic review")
        ),
        horizontal=True,
    )
    strictness = st.slider(
        "Screening strictness",
        min_value=1,
        max_value=5,
        value=existing.get("strictness", 3),
        help="1 = cast a wide net, 5 = highly selective",
        format="%d",
    )
    st.caption(
        {1: "Very inclusive — keep anything potentially relevant",
         2: "Inclusive — lean towards inclusion",
         3: "Balanced",
         4: "Selective — require strong relevance",
         5: "Very selective — strict criteria only"}[strictness]
    )

with col_b:
    target_size = st.number_input(
        "Target corpus size (approx. final papers)",
        min_value=5,
        max_value=500,
        value=existing.get("target_corpus_size", 50),
        step=5,
    )
    hitl_enabled = st.checkbox(
        "Human-in-the-loop review (review borderline papers)",
        value=existing.get("hitl_enabled", True),
    )
    enable_snowballing = st.checkbox(
        "Enable citation snowballing",
        value=existing.get("enable_snowballing", True),
    )
    if enable_snowballing:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            max_snowball_rounds = st.number_input(
                "Max snowball rounds",
                min_value=1, max_value=10,
                value=existing.get("max_snowball_rounds", 3),
            )
        with col_s2:
            snowball_direction = st.selectbox(
                "Snowball direction",
                options=["both", "backward", "forward"],
                index=["both", "backward", "forward"].index(
                    existing.get("snowball_direction", "both")
                ),
            )

col_c, col_d = st.columns(2)
with col_c:
    inclusion_criteria = st.text_area(
        "Inclusion criteria",
        value=existing.get("inclusion_criteria", ""),
        height=120,
        placeholder="e.g. Empirical studies, adult participants (18+), outcomes measured...",
    )
with col_d:
    exclusion_criteria = st.text_area(
        "Exclusion criteria",
        value=existing.get("exclusion_criteria", ""),
        height=120,
        placeholder="e.g. Animal studies, non-peer-reviewed, case reports...",
    )

# ── 1.4 Launch ─────────────────────────────────────────────────────────────────
st.divider()

cfg = {
    "research_question": research_question,
    "review_type": review_type,
    "strictness": strictness,
    "keywords": keywords,
    "exclude_keywords": exclude_keywords,
    "year_min": year_range[0],
    "year_max": year_range[1],
    "disciplines": disciplines,
    "document_types": document_types,
    "language": language,
    "min_citations": min_citations,
    "oa_only": oa_only,
    "target_corpus_size": int(target_size),
    "hitl_enabled": hitl_enabled,
    "enable_snowballing": enable_snowballing,
    "max_snowball_rounds": int(max_snowball_rounds) if enable_snowballing else 0,
    "snowball_direction": snowball_direction if enable_snowballing else "both",
    "inclusion_criteria": inclusion_criteria,
    "exclusion_criteria": exclusion_criteria,
}

col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    if st.button(
        "🔍 Generate Search Strategy",
        type="secondary",
        use_container_width=True,
        disabled=not research_question.strip(),
        help="Preview the search queries before running the full pipeline",
    ):
        _launch(cfg, query_only=True)

with col2:
    if st.button(
        "🚀 Launch Full Review",
        type="primary",
        use_container_width=True,
        disabled=not research_question.strip() or not st.session_state.get("openai_api_key"),
    ):
        _launch(cfg, query_only=False)

with col3:
    if st.button("💾 Save Config", use_container_width=True):
        _save_config(cfg)
        st.success("Saved!")

if not research_question.strip():
    st.caption("Enter a research question above to enable launch.")
elif not st.session_state.get("openai_api_key"):
    st.caption("Add your OpenAI API key in the sidebar to launch.")
