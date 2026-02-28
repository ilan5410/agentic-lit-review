"""Pipeline Orchestrator — state machine coordinating all agents."""
from __future__ import annotations

from typing import Callable

from data import database
from agents.query_agent import QueryAgent
from agents.search_agent import SearchAgent
from agents.screening_agent import ScreeningAgent
from agents.quality_agent import QualityAgent
from agents.snowballing_agent import SnowballingAgent
from agents.synthesis_agent import SynthesisAgent
import config

# Pipeline stages (stored in session_state["pipeline_stage"])
STAGES = [
    "IDLE",
    "QUERY_FORMULATION",
    "QUERY_APPROVAL",
    "SEARCHING",
    "DEDUPLICATION",
    "SCREENING_PASS_1",
    "HITL_REVIEW",
    "SNOWBALLING",
    "QUALITY_ASSESSMENT",
    "SYNTHESIS",
    "COMPLETE",
]


class Orchestrator:
    """
    Coordinates the literature review pipeline.
    All mutable state is pushed to DuckDB + the provided session_state dict.
    The progress_callback is called with a string message on each step.
    """

    def __init__(
        self,
        db_conn,
        session_state: dict,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.conn = db_conn
        self.state = session_state
        self.log = progress_callback or (lambda msg: None)
        self._api_key = config.get_openai_key()
        self._openalex_email = config.get_openalex_email()
        self._ss_key = config.get_ss_key()

    # ── Stage helpers ──────────────────────────────────────────────────────────

    def get_stage(self) -> str:
        return self.state.get("pipeline_stage", "IDLE")

    def set_stage(self, stage: str) -> None:
        self.state["pipeline_stage"] = stage
        database.log_event(self.conn, stage, f"Entering stage: {stage}")
        self.log(f"── Stage: {stage} ──")

    def cfg(self) -> dict:
        return self.state.get("review_config", {})

    # ── Main entry points ──────────────────────────────────────────────────────

    def run_query_formulation(self) -> dict:
        """Run Agent 1: formulate search queries. Returns query dict."""
        self.set_stage("QUERY_FORMULATION")
        agent = QueryAgent(self._api_key, self.log)
        queries = agent.formulate_queries(
            self.cfg().get("research_question", ""),
            self.cfg(),
        )
        self.state["generated_queries"] = queries

        # Flatten for DB storage
        flat_queries = []
        for q in queries.get("openalex_queries", []):
            flat_queries.append({"api": "openalex", "query_text": q["query"], "description": q.get("description", "")})
        for q in queries.get("semantic_scholar_queries", []):
            flat_queries.append({"api": "semantic_scholar", "query_text": q["query"], "description": q.get("description", "")})
        database.save_queries(self.conn, flat_queries)

        self.set_stage("QUERY_APPROVAL")
        return queries

    def run_search(self) -> int:
        """Run Agent 2: execute approved queries."""
        self.set_stage("SEARCHING")
        queries = self.state.get("generated_queries", {})
        agent = SearchAgent(
            self.conn, self._openalex_email, self._ss_key, self.log
        )
        total = agent.run(queries, self.cfg())
        self.set_stage("DEDUPLICATION")
        database.log_event(self.conn, "DEDUPLICATION", f"{total} unique papers after deduplication")
        self.log(f"Deduplication complete: {total} unique papers.")
        return total

    def run_screening_pass1(self) -> dict:
        """Run Agent 3 Pass 1. Returns counts; does NOT advance stage."""
        self.set_stage("SCREENING_PASS_1")
        agent = ScreeningAgent(self._api_key, self.conn, self.log)
        counts = agent.run_pass1(self.cfg())
        # Finalize non-borderline INCLUDEs regardless of HITL
        agent.finalize_included()
        return counts

    def resume_after_hitl(self) -> None:
        """Apply human decisions for borderline papers."""
        agent = ScreeningAgent(self._api_key, self.conn, self.log)
        agent.apply_human_decisions()
        agent.finalize_included()

    def run_snowballing(self) -> int:
        """Run Agent 6: snowballing. Does NOT advance stage."""
        self.set_stage("SNOWBALLING")
        agent = SnowballingAgent(
            self._api_key, self.conn, self._openalex_email, self.log
        )
        return agent.run(self.cfg())

    def run_quality_assessment(self) -> None:
        """Run Agent 4: quality assessment. Does NOT advance stage."""
        self.set_stage("QUALITY_ASSESSMENT")
        agent = QualityAgent(self._api_key, self.conn, self.log)
        agent.run(self.cfg())

    def run_synthesis(self) -> dict:
        """Run Agent 5: synthesis (includes relevance scoring). Does NOT advance stage."""
        self.set_stage("SYNTHESIS")
        agent = SynthesisAgent(self._api_key, self.conn, self.log)
        return agent.run(self.cfg())

    def run_relevance_scoring(self) -> None:
        """Re-run relevance scoring independently (e.g. from the Results page)."""
        from agents.relevance_agent import RelevanceAgent
        agent = RelevanceAgent(self._api_key, self.conn, self.log)
        agent.run(self.cfg().get("research_question", ""))
