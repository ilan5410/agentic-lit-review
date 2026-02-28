"""All LLM prompt templates for the literature review pipeline."""

# ── Query Formulation ──────────────────────────────────────────────────────────

QUERY_SYSTEM = """You are an expert research librarian helping a researcher conduct a systematic literature review.
Your job is to transform a research question into optimised search queries for academic databases.
Always respond with valid JSON."""

QUERY_USER = """Research question: {research_question}

Review type: {review_type}
Year range: {year_min}–{year_max}
Keywords to include: {keywords}
Keywords to exclude: {exclude_keywords}
Disciplines: {disciplines}
Document types: {document_types}
Inclusion criteria: {inclusion_criteria}
Exclusion criteria: {exclusion_criteria}

Generate search queries optimised for two databases:

1. OpenAlex — use PLAIN KEYWORD queries only. The "query" field is passed to the ?search= parameter,
   which accepts simple text like a Google search. Do NOT use field prefixes (title.search:, abstract.search:),
   do NOT use parentheses or boolean operators. Just write the core terms, e.g.:
   "populism causes economic inequality" or "right-wing parties electoral support".
   Keep queries under 10 words. Provide 3–5 distinct queries covering different angles.

2. Semantic Scholar — natural language or keyword queries work best here too.
   Same rule: plain text, no special syntax.

Return a JSON object with this exact structure:
{{
  "openalex_queries": [
    {{"query": "<plain keyword string, no field: syntax>", "description": "<what this query targets>"}},
    ...
  ],
  "semantic_scholar_queries": [
    {{"query": "<plain keyword string>", "description": "<what this query targets>"}},
    ...
  ],
  "suggested_concepts": ["<concept name>", ...],
  "notes_for_user": "<any observations about the research question framing, gaps, or suggestions>"
}}

Provide 3–6 queries per database covering different angles of the topic. For a {review_type}, calibrate exhaustiveness accordingly (systematic = very comprehensive, rapid = focused)."""


# ── Screening ──────────────────────────────────────────────────────────────────

SCREENING_SYSTEM = """You are a systematic review screening assistant. You evaluate papers for inclusion in a literature review based on provided criteria.
Be consistent, fair, and clearly justify each decision. Always respond with valid JSON."""

SCREENING_USER = """Research question: {research_question}
Review type: {review_type}
Screening strictness: {strictness}/5 (1=inclusive, 5=very selective)
Inclusion criteria: {inclusion_criteria}
Exclusion criteria: {exclusion_criteria}

Screen the following papers and classify each as INCLUDE, EXCLUDE, or BORDERLINE.

Papers to screen:
{papers_json}

Return a JSON object with this structure:
{{
  "decisions": [
    {{
      "id": "<paper id>",
      "decision": "INCLUDE" | "EXCLUDE" | "BORDERLINE",
      "confidence": <0–100>,
      "reason": "<one sentence explaining the decision>",
      "exclusion_category": "<if EXCLUDE: wrong_topic | wrong_method | wrong_population | wrong_timeframe | duplicate | low_quality | other>"
    }},
    ...
  ]
}}

Screen ALL {n_papers} papers. Return exactly {n_papers} decisions."""


# ── Quality Assessment ─────────────────────────────────────────────────────────

QUALITY_SYSTEM = """You are an expert in research methodology and systematic review quality assessment.
Evaluate papers rigorously but fairly. Always respond with valid JSON."""

QUALITY_USER = """Research question: {research_question}
Review type: {review_type}

Assess the methodological quality of this paper:

Title: {title}
Abstract: {abstract}
Year: {year}
Journal: {journal}
Citation count: {citation_count}
Document type: {document_type}

Rate the quality on a 0–100 scale and identify any concerns.

Return JSON:
{{
  "quality_score": <0–100>,
  "strengths": ["<strength 1>", ...],
  "concerns": ["<concern 1>", ...],
  "quality_notes": "<2–3 sentence summary of the quality assessment>",
  "flag": "<none | low_citations | predatory_journal_risk | methodology_weak | retraction_risk>"
}}"""


# ── Synthesis ──────────────────────────────────────────────────────────────────

CLUSTER_LABEL_SYSTEM = """You are a research synthesis expert. Given a list of paper titles and abstracts,
provide a concise thematic label (4–8 words) for the cluster and a one-paragraph summary."""

CLUSTER_LABEL_USER = """These papers form a thematic cluster. Read their titles and abstracts and:
1. Give a 4–8 word thematic label
2. Write a paragraph summarising the cluster's key themes and findings

Papers:
{papers_text}

Return JSON:
{{
  "label": "<4–8 word cluster label>",
  "summary": "<paragraph summary of this cluster>"
}}"""

SYNTHESIS_SYSTEM = """You are an expert academic researcher producing a literature synthesis for a systematic review.
Write clearly, analytically, and at a level appropriate for an academic methods section."""

SYNTHESIS_USER = """Research question: {research_question}
Review type: {review_type}
Total papers included: {n_papers}

Cluster summaries:
{cluster_summaries}

Based on these papers, write a comprehensive literature synthesis including:
1. A narrative overview of the literature landscape
2. Key themes, consensus positions, and areas of agreement
3. Significant debates, contradictions, or unresolved tensions
4. Research gaps and underrepresented areas
5. Methodological observations across the corpus

Return JSON:
{{
  "narrative_overview": "<2–3 paragraph overview>",
  "key_themes": ["<theme 1>", "<theme 2>", ...],
  "consensus_points": ["<consensus 1>", ...],
  "key_debates": ["<debate 1>", ...],
  "research_gaps": ["<gap 1>", ...],
  "methodological_observations": "<paragraph>",
  "seminal_papers_notes": "<paragraph about the most central/influential papers>"
}}"""
