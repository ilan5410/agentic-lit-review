import os

# ── LLM Models ────────────────────────────────────────────────────────────────
QUERY_MODEL = "gpt-4o"
SCREENING_MODEL = "gpt-4o-mini"
QUALITY_MODEL = "gpt-4o"
SYNTHESIS_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-small"

# ── API Endpoints ──────────────────────────────────────────────────────────────
OPENALEX_BASE = "https://api.openalex.org"
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"

# ── Pipeline Defaults ──────────────────────────────────────────────────────────
DEFAULT_TARGET_CORPUS_SIZE = 50
DEFAULT_MAX_SNOWBALL_ROUNDS = 3
DEFAULT_MIN_YIELD_RATE = 0.02
DEFAULT_MAX_CANDIDATES_PER_ROUND = 2000
DEFAULT_SCREENING_STRICTNESS = 3
DEFAULT_SCREENING_BATCH_SIZE = 20  # Papers per LLM call in screening
SCREENING_MAX_WORKERS = 12         # Concurrent LLM calls during screening
QUALITY_MAX_WORKERS = 8            # Concurrent LLM calls during quality assessment
# Tune these down if you hit 429 rate-limit errors (depends on your OpenAI tier).

# ── Rate Limits ────────────────────────────────────────────────────────────────
OPENALEX_RATE_LIMIT = 10           # req/sec polite pool
SS_RATE_LIMIT_UNAUTH = 1           # req/sec
SS_RATE_LIMIT_AUTH = 10            # req/sec


def get_openai_key() -> str:
    try:
        import streamlit as st
        val = st.session_state.get("openai_api_key", "")
        if val:
            return val
        return st.secrets.get("OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    except Exception:
        return os.environ.get("OPENAI_API_KEY", "")


def get_openalex_email() -> str:
    try:
        import streamlit as st
        return st.secrets.get("OPENALEX_EMAIL", "") or os.environ.get("OPENALEX_EMAIL", "")
    except Exception:
        return os.environ.get("OPENALEX_EMAIL", "")


def get_ss_key() -> str:
    try:
        import streamlit as st
        return st.secrets.get("SEMANTIC_SCHOLAR_API_KEY", "") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    except Exception:
        return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
