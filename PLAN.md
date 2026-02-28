# PLAN.md — Agentic Literature Review Tool

## Project Overview

Build a **Streamlit app** that provides an agentic, multi-step literature review pipeline. The user describes a research topic in natural language (with optional structured constraints), and a team of OpenAI-powered agents searches academic databases, screens papers, and produces a curated, defensible literature corpus with synthesis.

The app connects to **OpenAlex** (271M+ works, best free coverage) as primary data source and **Semantic Scholar** (200M papers, SPECTER2 embeddings) as secondary source. Agents use the **OpenAI API** (GPT-4o for reasoning, GPT-4o-mini for bulk screening) to orchestrate the review pipeline.

---

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | **Streamlit** (mature ecosystem, large community, built-in progress components, free cloud deployment) |
| LLM | **OpenAI API** — GPT-4o for reasoning, GPT-4o-mini for bulk screening |
| Primary paper database | **OpenAlex API** (free, no auth, 271M+ works, best coverage at 98.6%) |
| Secondary paper database | **Semantic Scholar API** (free, 200M papers, SPECTER2 embeddings, TLDR summaries) |
| Local storage | **DuckDB** (fast, in-process, excellent Python support) |
| Embeddings | **OpenAI text-embedding-3-small** (for semantic similarity + clustering) |
| Visualization | plotly (interactive cluster map, charts) |
| Export | pandas (CSV/Excel), bibtexparser (BibTeX), RIS generation, python-docx (reports) |
| Async/concurrency | asyncio + httpx for parallel API calls |
| **Deployment** | **Streamlit Community Cloud** (free, GitHub-integrated auto-deploy) or Docker → any cloud |

### Why Streamlit?
- **Mature ecosystem**: Largest community among Python app frameworks. Abundant tutorials, StackOverflow answers, and third-party components.
- **Built-in progress UX**: `st.status`, `st.spinner`, `st.progress` are purpose-built for showing long-running pipeline stages — exactly what this app needs.
- **`st.session_state`**: Straightforward state management for pipeline stages, cached papers, and user decisions on borderline papers.
- **`st.data_editor`**: Interactive editable tables — perfect for the paper review table where users mark borderline papers as include/exclude.
- **Free cloud deployment**: Streamlit Community Cloud deploys from a GitHub repo with one click. Push to main → auto-redeploy.
- **`@st.cache_data`**: Cache expensive computations (search results, embeddings) so page re-renders are cheap.
- **Managing re-renders**: Streamlit re-runs the full script on input changes, but this is manageable: heavy work lives in cached functions and `st.session_state`, so re-renders only touch the UI layer. Use `st.fragment` (experimental) to isolate interactive sections that shouldn't trigger full re-runs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Streamlit App (Python)                  │
│  Sidebar config │ Progress area │ Results tabs │ Export    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│              Orchestrator (Python + OpenAI)                │
│  Manages pipeline state, logs decisions, handles errors    │
│  State lives in st.session_state                           │
└────┬──────────┬──────────┬──────────┬───────────────────┘
     │          │          │          │
     ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐
│ Query  │ │ Search │ │ Screen │ │Synthesis │
│ Agent  │ │ Agent  │ │ Agent  │ │  Agent   │
└────┬───┘ └───┬────┘ └───┬────┘ └────┬─────┘
     │         │          │           │
     ▼         ▼          ▼           ▼
┌──────────────────────────────────────────────────────────┐
│          Data Layer: APIs + Local DuckDB Cache             │
│   OpenAlex API │ Semantic Scholar API │ Unpaywall (OA)     │
└──────────────────────────────────────────────────────────┘
```

---

## File Structure

```
lit-review-app/
├── app.py                     # Streamlit app entry point (main page: input + launch)
├── config.py                  # API keys, model names, defaults
├── requirements.txt
├── README.md
├── PLAN.md
├── .streamlit/
│   └── config.toml            # Streamlit theme + settings
│
├── pages/
│   ├── 1_📋_Define_Review.py  # Topic definition + screening config (if using multi-page)
│   ├── 2_🔄_Progress.py       # Real-time agent activity log + HITL queue
│   ├── 3_📊_Results.py        # Paper table, PRISMA, cluster map, synthesis
│   └── 4_📥_Export.py         # Download buttons + summary
│
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py        # Pipeline controller, state machine (uses st.session_state)
│   ├── query_agent.py         # Research question → search queries
│   ├── search_agent.py        # Executes searches against APIs
│   ├── screening_agent.py     # Title/abstract + full-text screening
│   ├── quality_agent.py       # Methodological quality assessment
│   ├── snowballing_agent.py   # Iterative citation network exploration
│   └── synthesis_agent.py     # Clustering, summarization, gap analysis
│
├── data/
│   ├── __init__.py
│   ├── openalex_client.py     # OpenAlex API wrapper
│   ├── semantic_scholar.py    # Semantic Scholar API wrapper
│   ├── database.py            # DuckDB schema + CRUD operations
│   └── exporters.py           # BibTeX, RIS, CSV, Excel export
│
└── utils/
    ├── __init__.py
    ├── llm.py                 # OpenAI API wrapper (chat + embeddings)
    ├── prompts.py             # All LLM prompt templates
    └── prisma.py              # PRISMA flow diagram generator
```

---

## UI Design (Streamlit Multi-Page App)

Streamlit's multi-page app structure uses the `pages/` directory. Each page is a separate Python file. The sidebar is shared across all pages and holds the API key input + navigation.

### Page 1: Define Review

This is the main input screen. The user configures the review here before launching.

#### Section 1.1 — Research Question (required)
- **Large text area**: Free-text description of the research topic. The user can be as vague ("impact of AI on healthcare") or precise ("effect of transformer-based NLP models on radiology report classification accuracy, 2020-2024") as they want.
- **Helper text**: "Describe your research question or topic of interest. Be as specific or broad as you like — the agents will refine the search strategy."

#### Section 1.2 — Structured Constraints (optional, collapsible)
Each of these is optional — they narrow the search if provided:

| Field | Type | Description |
|---|---|---|
| **Keywords** | Text input (comma-separated) | Specific terms that must appear |
| **Exclude keywords** | Text input (comma-separated) | Terms to exclude |
| **Year range** | Range slider (1950–2026) | Publication date window |
| **Disciplines / fields** | Multi-select dropdown | OpenAlex concepts/topics (auto-populated) |
| **Language** | Dropdown | Filter by publication language |
| **Document types** | Multi-select | Journal article, review, conference paper, preprint, book chapter |
| **Journal whitelist** | Text input | Only include papers from these journals |
| **Journal blacklist** | Text input | Exclude papers from these journals |
| **Minimum citation count** | Numeric input | Floor for citation filtering |
| **Open access only** | Checkbox | Restrict to OA papers |
| **Geographic focus** | Text input | Country/region focus (if relevant) |

#### Section 1.3 — Screening Configuration

| Field | Type | Description |
|---|---|---|
| **Review type** | Radio buttons | Systematic review · Scoping review · Rapid evidence assessment · Narrative review |
| **Screening strictness** | Slider (1–5) | 1 = "Cast a wide net" → 5 = "Highly selective" — controls the LLM screening threshold |
| **Inclusion criteria** | Text area | Free-text: what must a paper address to be included? |
| **Exclusion criteria** | Text area | Free-text: what disqualifies a paper? |
| **Methodological filter** | Multi-select | RCT, quasi-experimental, observational, qualitative, theoretical, meta-analysis, simulation... |
| **Target corpus size** | Numeric input (default 50) | Approximate number of final papers desired |
| **Enable snowballing** | Checkbox (default on) | After initial screening, iteratively follow citation networks to find missed papers |
| **Max snowball rounds** | Numeric input (default 3) | Hard cap on snowballing iterations (most reviews converge by round 2–3) |
| **Snowball direction** | Radio buttons | Both (forward + backward) · Backward only (references) · Forward only (citing papers) |
| **Human-in-the-loop** | Checkbox (default on) | Pause on borderline papers for user decision |

#### Section 1.4 — Launch
- **"Generate Search Strategy" button**: Runs the Query Agent, shows proposed queries for user approval before searching.
- **"Launch Full Review" button**: Runs the entire pipeline end-to-end (with optional HITL pauses).

---

### Page 2: Review Progress (live dashboard)

Shows pipeline status as agents work. Uses `st.status` containers for each pipeline stage and `st.empty` placeholders for live-updating metrics.

- **Pipeline stage indicator**: Query formulation → Search → Deduplication → Screening (Pass 1) → Screening (Pass 2) → Quality assessment → Synthesis
- **Agent activity log**: Scrolling text log of what each agent is doing in real time (e.g., "Screening Agent: Evaluated paper #127/342 — EXCLUDED (reason: not empirical)")
- **PRISMA flow diagram** (auto-updating): 
  - Records identified through database searching: N
  - Records after deduplication: N
  - Records screened (title/abstract): N
  - Records excluded with reasons: N
  - Full-text articles assessed for eligibility: N
  - Studies included in final review: N
- **Borderline papers queue** (if HITL enabled): Uses `st.data_editor` with a checkbox column for Include/Exclude decisions, showing title + abstract + agent's reasoning. Alternatively, `st.expander` cards with `st.button` pairs.

---

### Page 3: Results Dashboard

Available after pipeline completes (or partially, as results come in).

#### 3.1 — Paper Table
Interactive `st.dataframe` (sortable, filterable, searchable) or `st.data_editor` with columns:
- Title (clickable → link to paper)
- Authors
- Year
- Journal / Source
- Relevance score (agent-assigned, 0–100)
- Quality score (agent-assigned)
- Citation count
- Inclusion status (Included / Excluded / Borderline)
- Agent's reasoning (expandable)
- Abstract (expandable)
- Open access link (if available)

#### 3.2 — Topic Cluster Map
- 2D scatter plot of papers using embeddings (UMAP or t-SNE dimensionality reduction)
- Points colored by cluster (auto-detected via HDBSCAN or similar)
- Hover shows title + authors
- Click shows full details
- Cluster labels generated by LLM (e.g., "Transformer architectures for medical imaging")

#### 3.3 — Summary Statistics
- Papers by year (bar chart)
- Papers by journal (bar chart, top 15)
- Papers by methodology (pie/donut chart)
- Citation distribution (histogram)
- Geographic distribution (if data available)

#### 3.4 — Literature Synthesis (AI-generated)
- **Narrative overview**: 1–2 page summary of the literature landscape
- **Per-cluster summaries**: Key findings, consensus, and contradictions within each topic cluster
- **Gap analysis**: What's underrepresented? What questions remain unanswered?
- **Key debates**: Where do authors disagree?
- **Seminal papers**: Most cited / most central to the network

---

### Page 4: Export

Uses `st.download_button` for each export format:

- **Download BibTeX** (.bib file for all included papers)
- **Download RIS** (.ris file for reference managers)
- **Download CSV / Excel** (full paper table with all metadata + agent scores)
- **Download PRISMA diagram** (as PNG or SVG)
- **Download narrative summary** (as Markdown or DOCX)
- **Download full audit trail** (JSON log of every agent decision with reasoning)

---

## Agent Pipeline — Detailed Specification

### Agent 0: Orchestrator (`orchestrator.py`)

The orchestrator is not an LLM agent — it's a Python state machine that manages the pipeline. All state is stored in `st.session_state` so it persists across Streamlit re-renders.

**Responsibilities:**
- Manages pipeline state (which stage is active, what's completed)
- Coordinates agent execution order
- Handles errors, retries, and rate limiting
- Maintains the DuckDB database
- Writes progress updates to `st.session_state` (read by the Progress page)
- Logs every decision for the audit trail

**State machine stages:**
```
IDLE → QUERY_FORMULATION → QUERY_APPROVAL → SEARCHING → DEDUPLICATION 
→ SCREENING_PASS_1 → HITL_REVIEW → SCREENING_PASS_2 → QUALITY_ASSESSMENT
→ SYNTHESIS → COMPLETE
```

---

### Agent 1: Query Formulation Agent (`query_agent.py`)

**Input:** User's research question + structured constraints
**Output:** A set of search queries optimized for each data source

**What it does:**
1. Takes the user's natural language description
2. Calls GPT-4o to:
   - Extract key concepts, synonyms, related terms
   - Generate Boolean-style search strings for OpenAlex's structured search
   - Generate natural language semantic queries for Semantic Scholar
   - Suggest OpenAlex concept/topic IDs to filter on
   - Identify potential gaps in the user's framing (e.g., "You mentioned X but might also want to consider Y")
3. Presents proposed queries to the user for approval/editing before execution

**Prompt strategy:**
- System prompt establishes role as expert research librarian
- Includes the user's review type (systematic vs. scoping etc.) to calibrate exhaustiveness
- Outputs structured JSON: `{ "openalex_queries": [...], "semantic_scholar_queries": [...], "suggested_concepts": [...], "notes_for_user": "..." }`

---

### Agent 2: Search Agent (`search_agent.py`)

**Input:** Approved search queries from Agent 1
**Output:** Raw paper metadata stored in DuckDB

**What it does:**
1. Executes queries against OpenAlex API:
   - Uses `/works` endpoint with filters (publication_year, type, concepts.id, etc.)
   - Paginates through results (cursor-based pagination)
   - Retrieves: title, authors, abstract (inverted index → reconstructed), year, journal, DOI, citation count, concepts, open access URL, referenced_works, cited_by_count
2. Executes queries against Semantic Scholar API:
   - Uses `/paper/search` endpoint for keyword search
   - Uses `/paper/search` with `fieldsOfStudy` filter
   - Retrieves: title, authors, abstract, year, venue, DOI, citation count, embedding (SPECTER2), references, citations, tldr
3. Deduplicates across sources (match on DOI, fallback to title+year fuzzy match)
4. Stores all results in DuckDB with provenance tracking (which source, which query)

**Rate limiting:**
- OpenAlex: polite pool (email in params), 100k/day — no practical limit
- Semantic Scholar: 1 request/second without API key, 10/sec with key

**Expected volume:** Depending on topic breadth, 200–2000 raw papers before screening.

---

### Agent 3: Screening Agent (`screening_agent.py`)

The core agent. Two-pass screening inspired by systematic review methodology.

#### Pass 1 — Title + Abstract Screening

**Input:** All deduplicated papers from DuckDB
**Output:** Inclusion/exclusion decision + reasoning for each paper

**What it does:**
1. For each paper, constructs a prompt containing:
   - The user's research question and inclusion/exclusion criteria
   - The paper's title and abstract
   - The screening strictness level
2. Calls GPT-4o-mini (cheap, fast — ~$0.15/1M input tokens) to classify:
   - `INCLUDE` — clearly relevant
   - `EXCLUDE` — clearly irrelevant, with reason category (wrong topic / wrong method / wrong population / wrong timeframe / etc.)
   - `BORDERLINE` — uncertain, needs human review
   - Confidence score (0–100)
   - One-line reasoning
3. Papers classified as `BORDERLINE` are queued for human review if HITL is enabled
4. **Batching strategy**: Send papers in batches of 5–10 per API call to reduce overhead (GPT-4o-mini handles this well)

**Cost estimate:**
- 500 papers × ~300 tokens/paper (title + abstract) = ~150k input tokens
- At GPT-4o-mini rates: ~$0.02 for the entire screening pass
- Even at 2000 papers: ~$0.08

#### Pass 2 — Deep Screening (optional, for systematic reviews)

**Input:** Papers that passed Pass 1
**Output:** Refined inclusion decisions with deeper analysis

**What it does:**
1. For included papers with available full text (via Unpaywall/CORE):
   - Download full text PDF or HTML
   - Extract methodology section, results, and conclusions
   - Run deeper relevance assessment against inclusion criteria
2. For papers without full text:
   - Use the abstract + citation context (what do citing papers say about this paper?)
   - Leverage Semantic Scholar's TLDR summaries if available
3. Classify with GPT-4o (higher quality model for this pass, fewer papers)

---

### Agent 4: Quality Assessment Agent (`quality_agent.py`)

**Input:** Included papers after screening
**Output:** Quality scores + quality assessment notes

**What it does:**
1. Assesses methodological quality adapted to the review type:
   - For empirical work: study design, sample size, controls, statistical rigor
   - For theoretical work: novelty, logical coherence, scope
   - For reviews: systematic methodology, comprehensiveness, recency
2. Checks citation network health:
   - Is this paper well-cited relative to its age?
   - Does it cite key works in the field?
   - Is it published in a reputable venue?
3. Flags potential issues:
   - Predatory journal indicators (check against known lists)
   - Retraction status (CrossRef retraction metadata)
   - Unusually high self-citation rates
4. Assigns quality score (0–100) with reasoning

**Model:** GPT-4o (needs nuanced judgment)

---

### Agent 5: Synthesis Agent (`synthesis_agent.py`)

**Input:** Final corpus of included papers with metadata, scores, and embeddings
**Output:** Structured literature synthesis

**What it does:**

1. **Cluster analysis:**
   - Compute embeddings for all included papers (OpenAI text-embedding-3-small on title+abstract, or use SPECTER2 from Semantic Scholar)
   - Cluster using HDBSCAN (handles varying cluster sizes, doesn't require predefined k)
   - Generate human-readable cluster labels via GPT-4o
   - Reduce to 2D via UMAP for visualization

2. **Narrative synthesis** (per cluster):
   - Feed cluster papers to GPT-4o with prompt: "Summarize the key findings, methodologies, and conclusions across these papers. Identify areas of consensus and disagreement."
   - Max ~20 papers per cluster per call; if more, summarize in hierarchical passes

3. **Overall synthesis:**
   - Combine cluster summaries into a coherent narrative
   - Generate gap analysis: "Based on these papers, what questions remain unanswered? What methodologies are underrepresented?"
   - Identify the most influential papers (by citation + centrality in the co-citation network)

4. **PRISMA diagram data:**
   - Aggregate counts at each pipeline stage
   - Generate the flow diagram data structure

---

### Agent 6: Snowballing Agent (iterative)

**Triggered if:** User enabled snowballing in config (on by default).

**What it does:**

Snowballing finds papers the keyword search missed by following the citation network of already-included papers. It runs in **iterative rounds** with a **smart stopping criterion** to avoid exponential blowup.

**Algorithm:**

```
round = 0
while True:
    round += 1
    
    # 1. Collect candidates
    candidates = set()
    for paper in newly_included_papers_this_round:
        # Backward snowballing: papers this one cites
        candidates |= get_references(paper)  # via OpenAlex referenced_works
        # Forward snowballing: papers that cite this one
        candidates |= get_citing_papers(paper)  # via OpenAlex cited_by
    
    # 2. Remove papers already in corpus (included or excluded)
    candidates -= already_seen_papers
    
    # 3. Screen candidates through Screening Agent (Pass 1)
    new_inclusions = screen(candidates)
    
    # 4. Check stopping criteria
    yield_rate = len(new_inclusions) / len(candidates) if candidates else 0
    
    stop_reasons = [
        len(new_inclusions) == 0,                          # No new papers found
        yield_rate < 0.02,                                  # Less than 2% hit rate
        round >= max_rounds (default 3),                    # Hard cap on iterations
        total_included >= target_corpus_size * 1.5,         # Exceeded target significantly
        len(candidates) > 5000,                             # Too many candidates (cost control)
    ]
    
    if any(stop_reasons):
        log_stopping_reason()
        break
    
    # 5. Prepare for next round
    newly_included_papers_this_round = new_inclusions
```

**Key parameters (user-configurable):**
- `max_snowball_rounds`: Default 3 (most reviews converge by round 2-3)
- `min_yield_rate`: Default 0.02 (stop if <2% of candidates are relevant)
- `snowball_directions`: "both" | "backward_only" | "forward_only"
- `max_candidates_per_round`: Default 2000 (cost control)

**Why iterative matters:**
- Round 1 typically catches the most important missed papers (the "obvious" ones the keyword search missed)
- Round 2 catches papers that are one hop further away in the citation network
- Round 3 rarely adds much — if it does, the original search was probably too narrow
- The yield rate drop-off is usually dramatic: 15% → 5% → 1% across rounds

**Cost control:**
- Each candidate only needs title+abstract screening (GPT-4o-mini)
- 1000 candidates ≈ $0.04 to screen
- Total snowballing cost for a typical review: $0.10–0.30

**Reporting:**
- The PRISMA diagram shows snowballing as a separate identification source
- Each round is logged: N candidates found → N screened → N included
- The user can see which included papers were found via snowballing vs. direct search

---

## Database Schema (DuckDB)

```sql
CREATE TABLE papers (
    id VARCHAR PRIMARY KEY,          -- Internal ID
    doi VARCHAR,
    title VARCHAR NOT NULL,
    abstract TEXT,
    authors JSON,                     -- [{name, orcid, affiliations}]
    year INTEGER,
    journal VARCHAR,
    source VARCHAR,                   -- 'openalex' | 'semantic_scholar'
    document_type VARCHAR,            -- article, review, conference, preprint...
    citation_count INTEGER,
    open_access_url VARCHAR,
    concepts JSON,                    -- OpenAlex concepts/topics
    embedding FLOAT[],               -- For clustering
    
    -- Pipeline fields
    query_source VARCHAR,             -- Which search query found this paper
    screening_pass1 VARCHAR,          -- INCLUDE | EXCLUDE | BORDERLINE
    screening_pass1_reason TEXT,
    screening_pass1_confidence FLOAT,
    screening_pass2 VARCHAR,
    screening_pass2_reason TEXT,
    human_decision VARCHAR,           -- If HITL: INCLUDE | EXCLUDE
    quality_score FLOAT,
    quality_notes TEXT,
    relevance_score FLOAT,
    cluster_id INTEGER,
    cluster_label VARCHAR,
    final_status VARCHAR,             -- INCLUDED | EXCLUDED
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    openalex_id VARCHAR,
    semantic_scholar_id VARCHAR
);

CREATE TABLE search_queries (
    id INTEGER PRIMARY KEY,
    query_text VARCHAR,
    target_api VARCHAR,               -- 'openalex' | 'semantic_scholar'
    results_count INTEGER,
    executed_at TIMESTAMP
);

CREATE TABLE pipeline_log (
    id INTEGER PRIMARY KEY,
    stage VARCHAR,
    message TEXT,
    details JSON,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE review_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    research_question TEXT,
    review_type VARCHAR,
    strictness INTEGER,
    inclusion_criteria TEXT,
    exclusion_criteria TEXT,
    year_min INTEGER,
    year_max INTEGER,
    target_corpus_size INTEGER,
    config_json JSON                   -- Full config dump
);
```

---

## API Integration Details

### OpenAlex API

**Base URL:** `https://api.openalex.org`
**Auth:** None required. Add `mailto=your@email.com` parameter for polite pool (faster responses).
**Rate limit:** 100,000 requests/day (polite pool), 10/sec max.

**Key endpoints:**
- `GET /works?search={query}&filter=publication_year:{min}-{max},type:{type}` — keyword search with filters
- `GET /works?filter=concepts.id:{concept_id}` — filter by OpenAlex concept
- `GET /works/{openalex_id}` — single work details
- `GET /concepts?search={term}` — find concept IDs
- `GET /works/{id}/referenced_works` — for snowballing
- Abstracts are returned as inverted index → need reconstruction: `{"InvertedIndex": {"word": [positions]}}`

**Pagination:** Cursor-based. Use `cursor=*` for first page, then follow `next_cursor`.

### Semantic Scholar API

**Base URL:** `https://api.semanticscholar.org/graph/v1`
**Auth:** Optional API key for higher rate limit (10 req/sec vs 1 req/sec).
**Rate limit:** 1 request/second (unauthenticated), 10/sec (authenticated).

**Key endpoints:**
- `GET /paper/search?query={query}&fields=title,abstract,authors,year,venue,citationCount,embedding,tldr` — keyword search
- `GET /paper/{paper_id}?fields=references,citations` — citation network
- `GET /paper/search?query={query}&fieldsOfStudy={field}` — field-specific search

### OpenAI API

**Models used:**
- `gpt-4o` — Query formulation, quality assessment, synthesis (high reasoning quality)
- `gpt-4o-mini` — Bulk screening Pass 1 (cheap, fast, good enough for classification)
- `text-embedding-3-small` — Paper embeddings for clustering

**Structured outputs:** Use `response_format={"type": "json_object"}` for screening and query formulation to ensure parseable responses.

---

## Implementation Phases

### Phase 1 — MVP (Core Pipeline) — ~1 week

**Goal:** Working end-to-end pipeline with basic UI.

1. Set up project structure, config, DuckDB schema
2. Implement OpenAlex client (search + pagination + abstract reconstruction)
3. Implement Query Agent (research question → OpenAlex search queries)
4. Implement Search Agent (execute queries, store in DuckDB, deduplicate)
5. Implement Screening Agent Pass 1 (title/abstract screening with GPT-4o-mini)
6. Build Streamlit UI:
   - Sidebar: API key input + review config
   - Main page: research question + basic constraints + launch button
   - Progress area using `st.status` containers
   - Results table using `st.dataframe`
   - CSV export via `st.download_button`
7. Wire up the pipeline: input → `st.session_state` → agents → results

**Deliverable:** User can enter a topic, get ~50 screened papers with relevance scores.

### Phase 2 — Enhanced Screening & HITL — ~1 week

1. Add Semantic Scholar as secondary source
2. Implement deduplication across sources (DOI + fuzzy title matching)
3. Add screening strictness slider + inclusion/exclusion criteria
4. Implement HITL borderline review queue in UI
5. Implement Quality Assessment Agent
6. Add PRISMA flow diagram (auto-generated)
7. Add structured constraints panel (year range, document types, etc.)

### Phase 3 — Synthesis & Visualization — ~1 week

1. Implement paper embedding computation
2. Implement clustering (HDBSCAN) + UMAP 2D projection
3. Build interactive cluster map (plotly scatter)
4. Implement Synthesis Agent (per-cluster + overall narrative)
5. Add gap analysis
6. Add summary statistics charts (papers by year, by journal, etc.)
7. Add BibTeX and RIS export

### Phase 4 — Deployment & Advanced Features — ~1 week

1. **Deploy to Streamlit Community Cloud** (connect GitHub repo, add secrets)
2. Add API key input field in sidebar (user provides their own OpenAI key)
3. Implement iterative snowballing agent (forward + backward, smart stopping)
4. Implement Screening Pass 2 (full-text when available, via Unpaywall)
5. Add journal quality checks (predatory journal detection)
6. Add retraction checking (CrossRef metadata)
7. Add full audit trail export (JSON log of every agent decision)
8. Add DOCX narrative report export
9. Polish UI: custom theme in `.streamlit/config.toml`, loading states, error handling

---

## Cost Estimates (Per Review)

| Component | Tokens (approx) | Cost (approx) |
|---|---|---|
| Query formulation (GPT-4o) | ~2k in + 1k out | $0.01 |
| Screening Pass 1 — 500 papers (GPT-4o-mini, batched) | ~200k in + 50k out | $0.05 |
| Screening Pass 1 — 2000 papers | ~800k in + 200k out | $0.18 |
| Quality assessment — 80 papers (GPT-4o) | ~100k in + 30k out | $0.65 |
| Synthesis — 50 papers (GPT-4o) | ~80k in + 10k out | $0.50 |
| Embeddings — 500 papers (text-embedding-3-small) | ~200k tokens | $0.004 |
| **Total (typical review, ~500 raw papers)** | | **~$1.20** |
| **Total (large review, ~2000 raw papers)** | | **~$2.50** |

OpenAlex and Semantic Scholar APIs are **free**.

---

## Key Design Principles

1. **Transparency over magic**: Every agent decision is logged with reasoning. The user can inspect why any paper was included or excluded. This makes the review defensible in a methods section.

2. **Human-in-the-loop by default**: The system should augment, not replace, the researcher. Borderline decisions go to the human. The user approves search queries before execution.

3. **Reproducibility**: The full configuration + search queries + agent decisions are exportable. Another researcher could audit or replicate the review.

4. **Cost efficiency**: Use GPT-4o-mini for bulk operations (screening), GPT-4o only where reasoning quality matters (synthesis, quality). Keep total cost under $5 even for large reviews.

5. **Graceful degradation**: If Semantic Scholar is down, fall back to OpenAlex only. If full text isn't available, screen on abstract only. If embeddings fail, skip clustering but still provide the paper list.

6. **Iterative refinement**: After seeing initial results, the user should be able to adjust criteria and re-screen without re-searching. The cached papers in DuckDB make this instant.

---

## Dependencies (`requirements.txt`)

```
streamlit>=1.37
httpx>=0.27
openai>=1.30
duckdb>=1.0
pandas>=2.2
plotly>=5.22
numpy>=1.26
scikit-learn>=1.4
hdbscan>=0.8
umap-learn>=0.5
bibtexparser>=2.0
python-docx>=1.1
```

---

## Environment Variables

```
OPENAI_API_KEY=sk-...
SEMANTIC_SCHOLAR_API_KEY=...          # Optional, for higher rate limits
OPENALEX_EMAIL=your@email.com         # For polite pool access
```

## Deployment

### Option A: Streamlit Community Cloud (Recommended — Free)

The simplest path. Connect your GitHub repo → auto-deploy. Free for public apps, unlimited.

**Setup:**
1. Push code to a GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click "New app" → select repo, branch, and `app.py`
4. Add secrets (OPENAI_API_KEY etc.) in the app dashboard under "Advanced settings" → "Secrets"
5. Deploy. Auto-redeploys on every push to main.

**Secrets management** (`.streamlit/secrets.toml` format in the dashboard):
```toml
OPENAI_API_KEY = "sk-..."
SEMANTIC_SCHOLAR_API_KEY = "..."
OPENALEX_EMAIL = "your@email.com"
```

Access in code via `st.secrets["OPENAI_API_KEY"]`.

**Caveats:**
- 1GB RAM limit per app (sufficient for most reviews)
- App sleeps after inactivity (cold start ~15s)
- Public repos required on free tier (but secrets are hidden)
- No persistent file storage — DuckDB database is ephemeral (recreated per session, which is fine since each review is a session)

### Option B: Docker → Any Cloud

For more control, private deployments, or persistent storage:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

Deploy to:
- **Google Cloud Run**: Serverless, scales to zero, ~$0 when idle. Excellent for this use case.
- **Azure App Service**: `az webapp create` with container deployment.
- **Railway / Render / Fly.io**: Simple PaaS options, free tiers available.
- **Heroku**: Works with the Docker container.

### Option C: Hugging Face Spaces (Free, public)

Good for sharing the tool publicly as a demo:
- Create a Space with SDK "streamlit"
- Free CPU tier available
- Very easy setup (similar to Streamlit Community Cloud)

### Recommended path:
1. **Develop locally** (`streamlit run app.py`)
2. **Deploy to Streamlit Community Cloud** (free, instant)
3. **Move to Docker + cloud** when you need persistence, privacy, or more resources

---

## User Authentication & API Key Management

Since this app calls the OpenAI API (which costs money), you need to decide who provides the API key:

**Option A — User provides their own key (simplest):**
- Add an API key input field in the UI (password-masked)
- Store in session only (never persisted)
- Each user pays their own OpenAI costs
- No auth system needed

**Option B — App owner provides the key (for team/demo use):**
- Store OPENAI_API_KEY as environment variable on the server
- Add basic authentication (username/password) to the Shiny app
- shinyapps.io Professional plan supports auth natively
- Or use a simple password gate in the app itself

**Recommendation for MVP:** Option A. Let users bring their own key. Add Option B later if deploying for a team.

---

- **PubMed integration**: Add NCBI/PubMed as third source for biomedical reviews (uses E-utilities API)
- **Full-text analysis**: If CORE or Unpaywall provides PDFs, could do deeper extraction with document parsing
- **Citation network visualization**: Interactive co-citation graph
- **Saved reviews**: Persist review configurations and results for later continuation
- **Multi-user**: Could be deployed on a server for team use (add auth)
- **Fine-tuned screening model**: After enough human decisions accumulate, could train a lightweight classifier to replace LLM screening for common domains
- **Integration with Zotero**: Direct export to Zotero library
