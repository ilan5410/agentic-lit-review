"""Query Formulation Agent — converts a research question into API search queries."""
from __future__ import annotations

from typing import Callable

from utils.llm import chat_completion_json
from utils.prompts import QUERY_SYSTEM, QUERY_USER
import config


class QueryAgent:
    def __init__(self, api_key: str, progress_callback: Callable[[str], None] | None = None):
        self.api_key = api_key
        self.log = progress_callback or (lambda msg: None)

    def formulate_queries(self, research_question: str, cfg: dict) -> dict:
        """
        Returns:
            {
                "openalex_queries": [{"query": ..., "description": ...}, ...],
                "semantic_scholar_queries": [...],
                "suggested_concepts": [...],
                "notes_for_user": "..."
            }
        """
        self.log("Query Agent: formulating search strategy…")

        prompt = QUERY_USER.format(
            research_question=research_question,
            review_type=cfg.get("review_type", "systematic review"),
            year_min=cfg.get("year_min", 1990),
            year_max=cfg.get("year_max", 2025),
            keywords=cfg.get("keywords") or "none specified",
            exclude_keywords=cfg.get("exclude_keywords") or "none specified",
            disciplines=", ".join(cfg.get("disciplines") or []) or "none specified",
            document_types=", ".join(cfg.get("document_types") or []) or "all",
            inclusion_criteria=cfg.get("inclusion_criteria") or "not specified",
            exclusion_criteria=cfg.get("exclusion_criteria") or "not specified",
        )

        result = chat_completion_json(
            messages=[
                {"role": "system", "content": QUERY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            model=config.QUERY_MODEL,
            api_key=self.api_key,
            temperature=0.3,
        )

        self.log(
            f"Query Agent: generated {len(result.get('openalex_queries', []))} OpenAlex queries "
            f"and {len(result.get('semantic_scholar_queries', []))} Semantic Scholar queries."
        )
        return result
