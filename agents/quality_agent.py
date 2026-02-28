"""Quality Assessment Agent — parallel methodological quality scoring."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from data import database
from utils.llm import chat_completion_json
from utils.prompts import QUALITY_SYSTEM, QUALITY_USER
import config


class QualityAgent:
    def __init__(
        self,
        api_key: str,
        db_conn,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.api_key = api_key
        self.conn = db_conn
        self.log = progress_callback or (lambda msg: None)

    def run(self, cfg: dict) -> None:
        """Assess quality of all INCLUDED papers in parallel."""
        papers = database.get_papers(self.conn, final_status="INCLUDED")
        unassessed = [p for p in papers if p.get("quality_score") is None]

        if not unassessed:
            self.log("Quality Agent: all included papers already assessed.")
            return

        self.log(
            f"Quality Agent: assessing {len(unassessed)} papers "
            f"({config.QUALITY_MAX_WORKERS} workers)…"
        )

        completed_count = 0
        lock = threading.Lock()

        def assess_paper(p: dict) -> tuple[str, dict]:
            """Returns (paper_id, result_dict)."""
            prompt = QUALITY_USER.format(
                research_question=cfg.get("research_question", ""),
                review_type=cfg.get("review_type", "systematic review"),
                title=p.get("title", ""),
                abstract=(p.get("abstract") or "")[:800],
                year=p.get("year", "unknown"),
                journal=p.get("journal", "unknown"),
                citation_count=p.get("citation_count", 0),
                document_type=p.get("document_type", "article"),
            )
            try:
                result = chat_completion_json(
                    messages=[
                        {"role": "system", "content": QUALITY_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    model=config.QUALITY_MODEL,
                    api_key=self.api_key,
                    temperature=0.2,
                )
                return p["id"], {
                    "quality_score": result.get("quality_score", 50),
                    "quality_notes": result.get("quality_notes", ""),
                    "quality_flag": result.get("flag", "none"),
                }
            except Exception as e:
                self.log(f"Quality Agent: failed for '{p.get('title','')[:40]}' — {e}")
                return p["id"], {"quality_score": 50, "quality_notes": "Assessment failed.", "quality_flag": "none"}

        # ── Run concurrently ───────────────────────────────────────────────────
        all_results: list[tuple[str, dict]] = []

        with ThreadPoolExecutor(max_workers=config.QUALITY_MAX_WORKERS) as executor:
            futures = {executor.submit(assess_paper, p): p for p in unassessed}
            for future in as_completed(futures):
                paper_id, result = future.result()
                with lock:
                    completed_count += 1
                    all_results.append((paper_id, result))
                    self.log(f"Quality Agent: {completed_count}/{len(unassessed)} papers assessed…")

        # ── Write to DB (single-threaded) ──────────────────────────────────────
        for paper_id, result in all_results:
            database.update_paper(self.conn, paper_id, **result)

        database.log_event(self.conn, "QUALITY_ASSESSMENT", f"Assessed {len(unassessed)} papers")
        self.log(f"Quality Agent: complete. {len(unassessed)} papers assessed.")
