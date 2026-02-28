"""Relevance Agent — scores included papers by semantic closeness to the research question."""
from __future__ import annotations

import re
from typing import Callable

import numpy as np

from data import database
from utils import llm as llm_utils
import config


class RelevanceAgent:
    def __init__(
        self,
        api_key: str,
        db_conn,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.api_key = api_key
        self.conn = db_conn
        self.log = progress_callback or (lambda msg: None)

    def run(self, research_question: str) -> None:
        """
        Compute relevance_score (0–100) for every included paper.

        Method:
        1. Embed the research question (1 API call).
        2. Retrieve stored paper embeddings from DB.
        3. Cosine similarity → scale to 0–100.
        4. Fall back to keyword overlap if no embeddings exist yet.
        """
        papers = database.get_papers(self.conn, final_status="INCLUDED")
        if not papers:
            return

        stored = database.get_embeddings(self.conn)
        embedding_map: dict[str, list[float]] = {pid: vec for pid, vec in stored}

        if not embedding_map:
            self.log("Relevance Agent: no embeddings found — using keyword scoring fallback.")
            self._keyword_score(papers, research_question)
            return

        self.log("Relevance Agent: embedding research question…")
        rq_vec = llm_utils.get_embeddings([research_question], self.api_key)[0]
        rq = np.array(rq_vec, dtype=np.float32)
        rq /= np.linalg.norm(rq) + 1e-9

        scored = 0
        for p in papers:
            vec = embedding_map.get(p["id"])
            if vec is None:
                continue
            v = np.array(vec, dtype=np.float32)
            v /= np.linalg.norm(v) + 1e-9
            # Dot product of unit vectors = cosine similarity ∈ [-1, 1]
            sim = float(np.dot(rq, v))
            # Map to 0–100: OpenAI embeddings cluster in [0.5, 1.0] for related text,
            # so we stretch that range rather than mapping the full [-1,1].
            score = round(max(0.0, min(100.0, (sim - 0.3) / 0.7 * 100)), 1)
            database.update_paper(self.conn, p["id"], relevance_score=score)
            scored += 1

        database.log_event(
            self.conn, "RELEVANCE_SCORING",
            f"Scored {scored}/{len(papers)} papers by semantic similarity",
        )
        self.log(f"Relevance Agent: scored {scored} papers.")

    # ── Keyword fallback ───────────────────────────────────────────────────────

    _STOPWORDS = {
        "the", "a", "an", "and", "or", "of", "in", "to", "for",
        "is", "are", "was", "were", "be", "been", "being",
        "that", "this", "which", "with", "by", "from", "as",
    }

    def _keyword_score(self, papers: list[dict], research_question: str) -> None:
        rq_words = self._tokenise(research_question)
        for p in papers:
            text = f"{p.get('title', '')} {p.get('abstract', '')}"
            paper_words = self._tokenise(text)
            overlap = len(rq_words & paper_words) / max(len(rq_words), 1)
            score = round(min(100.0, overlap * 150), 1)
            database.update_paper(self.conn, p["id"], relevance_score=score)

    def _tokenise(self, text: str) -> set[str]:
        words = re.sub(r"[^\w\s]", "", text.lower()).split()
        return {w for w in words if w not in self._STOPWORDS and len(w) > 2}
