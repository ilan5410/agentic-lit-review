"""Search Agent — executes queries against OpenAlex and Semantic Scholar, deduplicates results."""
from __future__ import annotations

from typing import Callable

from data import openalex_client, semantic_scholar, database
import config


class SearchAgent:
    def __init__(
        self,
        db_conn,
        openalex_email: str,
        ss_api_key: str,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.conn = db_conn
        self.openalex_email = openalex_email
        self.ss_api_key = ss_api_key
        self.log = progress_callback or (lambda msg: None)

    def run(self, queries: dict, cfg: dict) -> int:
        """Execute all search queries and store results. Returns total papers stored."""
        total_inserted = 0
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()

        year_min = cfg.get("year_min")
        year_max = cfg.get("year_max")
        doc_types = cfg.get("document_types") or []
        max_per_query = max(50, cfg.get("target_corpus_size", 50) * 4)

        # ── OpenAlex ──────────────────────────────────────────────────────────
        oa_queries = queries.get("openalex_queries", [])
        for i, q in enumerate(oa_queries):
            self.log(f"Search Agent: OpenAlex query {i+1}/{len(oa_queries)}: '{q['query'][:60]}…'")
            try:
                papers = openalex_client.search_works(
                    query=q["query"],
                    email=self.openalex_email,
                    year_min=year_min,
                    year_max=year_max,
                    doc_types=doc_types if doc_types else None,
                    max_results=max_per_query,
                    query_source=f"openalex:{i+1}",
                    progress_callback=self.log,
                )
                unique = self._deduplicate(papers, seen_dois, seen_titles)
                n = database.upsert_papers(self.conn, unique)
                total_inserted += n
                database.log_event(
                    self.conn, "SEARCHING",
                    f"OpenAlex query {i+1}: found {len(papers)}, {n} new after dedup",
                )
                self.log(f"Search Agent: OpenAlex query {i+1} → {len(papers)} results, {n} new.")
            except Exception as e:
                self.log(f"Search Agent: OpenAlex query {i+1} failed — {e}")

        # ── Semantic Scholar ───────────────────────────────────────────────────
        ss_queries = queries.get("semantic_scholar_queries", [])
        for i, q in enumerate(ss_queries):
            self.log(f"Search Agent: Semantic Scholar query {i+1}/{len(ss_queries)}: '{q['query'][:60]}…'")
            try:
                papers = semantic_scholar.search_papers(
                    query=q["query"],
                    api_key=self.ss_api_key,
                    year_min=year_min,
                    year_max=year_max,
                    max_results=max_per_query // 2,
                    query_source=f"ss:{i+1}",
                    progress_callback=self.log,
                )
                unique = self._deduplicate(papers, seen_dois, seen_titles)
                n = database.upsert_papers(self.conn, unique)
                total_inserted += n
                database.log_event(
                    self.conn, "SEARCHING",
                    f"Semantic Scholar query {i+1}: found {len(papers)}, {n} new after dedup",
                )
                self.log(f"Search Agent: Semantic Scholar query {i+1} → {len(papers)} results, {n} new.")
            except Exception as e:
                self.log(f"Search Agent: Semantic Scholar query {i+1} failed — {e}")

        self.log(f"Search Agent: complete. {total_inserted} unique papers stored.")
        database.log_event(self.conn, "SEARCHING", f"Total unique papers: {total_inserted}")
        return total_inserted

    def _deduplicate(
        self, papers: list[dict], seen_dois: set[str], seen_titles: set[str]
    ) -> list[dict]:
        unique: list[dict] = []
        for p in papers:
            doi = (p.get("doi") or "").lower().strip()
            title_key = self._title_key(p.get("title", ""))

            if doi and doi in seen_dois:
                continue
            if title_key in seen_titles:
                continue

            if doi:
                seen_dois.add(doi)
            seen_titles.add(title_key)
            unique.append(p)
        return unique

    @staticmethod
    def _title_key(title: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]", "", title.lower())[:60]
