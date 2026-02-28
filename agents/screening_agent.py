"""Screening Agent — parallel title/abstract screening."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from data import database
from utils.llm import chat_completion_json
from utils.prompts import SCREENING_SYSTEM, SCREENING_USER
import config


class ScreeningAgent:
    def __init__(
        self,
        api_key: str,
        db_conn,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.api_key = api_key
        self.conn = db_conn
        self.log = progress_callback or (lambda msg: None)

    def run_pass1(self, cfg: dict) -> dict[str, int]:
        """
        Screen all unscreened papers in parallel batches.
        LLM calls run concurrently; DB writes happen after all futures complete.
        Returns counts: {"include": N, "exclude": N, "borderline": N}
        """
        papers = database.get_papers(self.conn)
        unscreened = [p for p in papers if not p.get("screening_pass1")]

        if not unscreened:
            self.log("Screening Agent: no unscreened papers.")
            return {"include": 0, "exclude": 0, "borderline": 0}

        batch_size = config.DEFAULT_SCREENING_BATCH_SIZE
        batches = [unscreened[i : i + batch_size] for i in range(0, len(unscreened), batch_size)]
        total = len(batches)
        self.log(
            f"Screening Agent: {len(unscreened)} papers → {total} batches "
            f"(batch size {batch_size}, {config.SCREENING_MAX_WORKERS} workers)…"
        )

        completed_count = 0
        lock = threading.Lock()

        def screen_batch(batch: list[dict]) -> list[dict]:
            papers_json = json.dumps([
                {
                    "id": p["id"],
                    "title": p.get("title", ""),
                    "abstract": (p.get("abstract") or "")[:600],
                }
                for p in batch
            ])
            prompt = SCREENING_USER.format(
                research_question=cfg.get("research_question", ""),
                review_type=cfg.get("review_type", "systematic review"),
                strictness=cfg.get("strictness", 3),
                inclusion_criteria=cfg.get("inclusion_criteria") or "not specified",
                exclusion_criteria=cfg.get("exclusion_criteria") or "not specified",
                papers_json=papers_json,
                n_papers=len(batch),
            )
            try:
                result = chat_completion_json(
                    messages=[
                        {"role": "system", "content": SCREENING_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    model=config.SCREENING_MODEL,
                    api_key=self.api_key,
                    temperature=0.1,
                )
                return result.get("decisions", [])
            except Exception as e:
                self.log(f"Screening Agent: batch failed — {e}. Marking as BORDERLINE.")
                return [
                    {"id": p["id"], "decision": "BORDERLINE", "confidence": 50, "reason": "API error"}
                    for p in batch
                ]

        # ── Run batches concurrently ───────────────────────────────────────────
        all_decisions: list[dict] = []

        with ThreadPoolExecutor(max_workers=config.SCREENING_MAX_WORKERS) as executor:
            futures = {executor.submit(screen_batch, batch): batch for batch in batches}
            for future in as_completed(futures):
                decisions = future.result()
                with lock:
                    completed_count += 1
                    all_decisions.extend(decisions)
                    self.log(
                        f"Screening Agent: {completed_count}/{total} batches done "
                        f"({completed_count * batch_size}/{len(unscreened)} papers)…"
                    )

        # ── Write all results to DB (single-threaded) ─────────────────────────
        counts = {"include": 0, "exclude": 0, "borderline": 0}
        for d in all_decisions:
            pid = d.get("id")
            if not pid:
                continue
            decision = d.get("decision", "BORDERLINE").upper()
            if decision not in ("INCLUDE", "EXCLUDE", "BORDERLINE"):
                decision = "BORDERLINE"

            database.update_paper(
                self.conn, pid,
                screening_pass1=decision,
                screening_pass1_reason=d.get("reason", ""),
                screening_pass1_confidence=d.get("confidence", 50),
            )
            if decision == "INCLUDE":
                counts["include"] += 1
            elif decision == "EXCLUDE":
                counts["exclude"] += 1
                database.update_paper(self.conn, pid, final_status="EXCLUDED")
            else:
                counts["borderline"] += 1

        database.log_event(self.conn, "SCREENING_PASS_1", "Pass 1 complete", counts)
        self.log(
            f"Screening Agent Pass 1 complete — "
            f"Include: {counts['include']}, Exclude: {counts['exclude']}, Borderline: {counts['borderline']}"
        )
        return counts

    def apply_human_decisions(self) -> None:
        """Move HITL decisions from human_decision field into final_status."""
        papers = database.get_papers(self.conn, pass1="BORDERLINE")
        for p in papers:
            decision = p.get("human_decision")
            if decision == "INCLUDE":
                database.update_paper(self.conn, p["id"], screening_pass1="INCLUDE", final_status=None)
            elif decision == "EXCLUDE":
                database.update_paper(self.conn, p["id"], final_status="EXCLUDED")

    def finalize_included(self) -> None:
        """Mark all INCLUDE papers without a final_status as INCLUDED."""
        papers = database.get_papers(self.conn)
        for p in papers:
            if p.get("screening_pass1") == "INCLUDE" and not p.get("final_status"):
                database.update_paper(self.conn, p["id"], final_status="INCLUDED")
