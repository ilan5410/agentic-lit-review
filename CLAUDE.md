# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Streamlit app providing an agentic, multi-step literature review pipeline. The user describes a research topic; a team of OpenAI-powered agents search academic databases, screen papers, and produce a curated corpus with synthesis.

**Status:** Planning phase. See `PLAN.md` for full specification.

## Commands

```bash
# Install dependencies (Python 3.10+)
pip install -r requirements.txt

# Run the app locally
streamlit run app.py

# Validate all module imports
python3 -c "import config; from utils import llm, prompts, prisma; from data import database, openalex_client, semantic_scholar, exporters; from agents import orchestrator"

# Environment variables (can also be entered in the app's sidebar)
export OPENAI_API_KEY=sk-...
export OPENALEX_EMAIL=your@email.com          # For polite pool (faster)
export SEMANTIC_SCHOLAR_API_KEY=...           # Optional, for higher rate limits
```

In Streamlit Community Cloud, secrets are stored in the app dashboard and accessed via `st.secrets["OPENAI_API_KEY"]`.

The OpenAI API key can also be entered interactively in the sidebar — it is stored only in `st.session_state` for the duration of the session.

## Architecture

```
app.py (entry point)
├── pages/            # Multi-page Streamlit UI
│   ├── 1_Define_Review.py   # Research question + constraints + screening config
│   ├── 2_Progress.py        # Live dashboard + HITL borderline paper queue
│   ├── 3_Results.py         # Paper table, cluster map, charts, synthesis
│   └── 4_Export.py          # BibTeX, RIS, CSV, DOCX, audit trail downloads
├── agents/           # LLM agent pipeline
│   ├── orchestrator.py      # State machine controller (not an LLM agent)
│   ├── query_agent.py       # Research question → optimized search queries
│   ├── search_agent.py      # Executes API searches, deduplicates, stores to DB
│   ├── screening_agent.py   # Two-pass title/abstract + full-text screening
│   ├── quality_agent.py     # Methodological quality scoring
│   ├── snowballing_agent.py # Iterative citation network exploration
│   └── synthesis_agent.py   # Clustering, summarization, gap analysis
├── data/
│   ├── openalex_client.py   # OpenAlex API wrapper
│   ├── semantic_scholar.py  # Semantic Scholar API wrapper
│   ├── database.py          # DuckDB schema + CRUD
│   └── exporters.py         # Export format generators
├── utils/
│   ├── llm.py               # OpenAI chat + embeddings wrapper
│   ├── prompts.py           # All LLM prompt templates
│   └── prisma.py            # PRISMA flow diagram generator
└── config.py                # Model names, defaults, constants
```

## Agent Pipeline

The **orchestrator** is a Python state machine (not an LLM). All pipeline state lives in `st.session_state` so it persists across Streamlit re-renders.

Pipeline stages: `IDLE → QUERY_FORMULATION → QUERY_APPROVAL → SEARCHING → DEDUPLICATION → SCREENING_PASS_1 → HITL_REVIEW → SCREENING_PASS_2 → QUALITY_ASSESSMENT → SYNTHESIS → COMPLETE`

| Agent | Model | Purpose |
|---|---|---|
| Query Agent | GPT-4o | Research question → Boolean + semantic search queries |
| Search Agent | — | Calls OpenAlex + Semantic Scholar APIs, deduplicates on DOI then fuzzy title+year |
| Screening Agent Pass 1 | GPT-4o-mini | Batched title/abstract screening (5–10 papers per call). Outputs: INCLUDE / EXCLUDE / BORDERLINE |
| Screening Agent Pass 2 | GPT-4o | Full-text screening for systematic reviews (via Unpaywall) |
| Quality Agent | GPT-4o | Methodological quality scoring, retraction checks, predatory journal detection |
| Snowballing Agent | GPT-4o-mini | Iterative citation network expansion; stops when yield rate < 2% or after max rounds |
| Synthesis Agent | GPT-4o | HDBSCAN clustering on embeddings, UMAP 2D projection, per-cluster + overall narrative, gap analysis |

## Key Technical Decisions

**LLM cost control:** Use GPT-4o-mini for high-volume operations (screening ~500–2000 papers at ~$0.05), GPT-4o only for reasoning-heavy tasks (synthesis, quality). Target total cost under $5 per review.

**State management:** All pipeline state in `st.session_state`. Heavy work in `@st.cache_data` functions. Use `st.fragment` to isolate interactive sections.

**DuckDB:** In-process, ephemeral per session (Streamlit Cloud has no persistent file storage). Papers table tracks the full pipeline: `screening_pass1`, `screening_pass2`, `human_decision`, `quality_score`, `final_status`, plus the paper embedding vector.

**Abstract reconstruction:** OpenAlex returns abstracts as an inverted index `{"word": [positions]}`. Reconstruct to plain text before use.

**Deduplication:** Match on DOI first; fall back to fuzzy title+year matching for papers without DOIs.

**Snowballing stopping criteria:** `len(new_inclusions) == 0` OR `yield_rate < 0.02` OR `round >= max_rounds` OR `total_included >= target_size * 1.5` OR `len(candidates) > 5000`.

**Structured LLM outputs:** Use `response_format={"type": "json_object"}` for screening and query formulation to ensure parseable JSON responses.

**Graceful degradation:** If Semantic Scholar is unavailable, fall back to OpenAlex only. If embeddings fail, skip clustering but retain the paper list. If full text unavailable, screen on abstract only.

## API Notes

- **OpenAlex:** No auth required. Add `mailto=` param for polite pool (10 req/sec). Cursor-based pagination. Endpoint: `https://api.openalex.org/works`.
- **Semantic Scholar:** Optional API key for 10 req/sec (vs 1 req/sec unauthenticated). Endpoint: `https://api.semanticscholar.org/graph/v1`.
- **OpenAI:** `gpt-4o` + `gpt-4o-mini` + `text-embedding-3-small`. Use `httpx` + `asyncio` for parallel API calls.

## Implementation Phases

- **Phase 1 (MVP):** OpenAlex search + Query Agent + Screening Pass 1 + basic Streamlit UI + CSV export
- **Phase 2:** Add Semantic Scholar, deduplication, HITL queue, Quality Agent, PRISMA diagram
- **Phase 3:** Embeddings, HDBSCAN clustering, UMAP, Synthesis Agent, cluster visualization
- **Phase 4:** Snowballing Agent, Screening Pass 2, BibTeX/RIS/DOCX export, Streamlit Community Cloud deployment
