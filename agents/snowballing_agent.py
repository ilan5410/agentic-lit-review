"""Snowballing Agent — iterative citation network expansion."""
from __future__ import annotations

from typing import Callable

from data import database, openalex_client
from agents.screening_agent import ScreeningAgent
import config


class SnowballingAgent:
    def __init__(
        self,
        api_key: str,
        db_conn,
        openalex_email: str,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.api_key = api_key
        self.conn = db_conn
        self.openalex_email = openalex_email
        self.log = progress_callback or (lambda msg: None)
        self.screener = ScreeningAgent(api_key, db_conn, progress_callback)

    def run(self, cfg: dict) -> int:
        """Run iterative snowballing. Returns total new papers included."""
        max_rounds = cfg.get("max_snowball_rounds", config.DEFAULT_MAX_SNOWBALL_ROUNDS)
        direction = cfg.get("snowball_direction", "both")
        min_yield = config.DEFAULT_MIN_YIELD_RATE
        max_candidates = config.DEFAULT_MAX_CANDIDATES_PER_ROUND
        target_size = cfg.get("target_corpus_size", config.DEFAULT_TARGET_CORPUS_SIZE)

        total_new_included = 0

        for round_num in range(1, max_rounds + 1):
            self.log(f"Snowballing Agent: Round {round_num}/{max_rounds}…")

            # Get currently included papers
            included = database.get_papers(self.conn, final_status="INCLUDED")
            if not included:
                self.log("Snowballing Agent: no included papers to snowball from.")
                break

            # Collect candidate IDs from citation network
            known_ids = self._get_all_known_ids()
            candidates: list[dict] = []

            for p in included:
                if len(candidates) >= max_candidates:
                    break
                oa_id = p.get("openalex_id")
                if not oa_id:
                    continue

                if direction in ("both", "backward"):
                    try:
                        refs = openalex_client.get_references(
                            oa_id, self.openalex_email, max_results=100
                        )
                        candidates.extend([r for r in refs if r["id"] not in known_ids])
                    except Exception as e:
                        self.log(f"Snowballing: backward lookup failed for {oa_id} — {e}")

                if direction in ("both", "forward"):
                    try:
                        citers = openalex_client.get_citing_papers(
                            oa_id, self.openalex_email, max_results=100
                        )
                        candidates.extend([r for r in citers if r["id"] not in known_ids])
                    except Exception as e:
                        self.log(f"Snowballing: forward lookup failed for {oa_id} — {e}")

            # Deduplicate candidates
            seen: set[str] = set()
            unique_candidates: list[dict] = []
            for c in candidates:
                if c["id"] not in seen and c["id"] not in known_ids:
                    seen.add(c["id"])
                    c["found_via"] = f"snowball_round_{round_num}"
                    unique_candidates.append(c)

            if not unique_candidates:
                self.log(f"Snowballing Agent: Round {round_num} — no new candidates. Stopping.")
                break

            self.log(
                f"Snowballing Agent: Round {round_num} — {len(unique_candidates)} candidates to screen."
            )

            # Insert candidates into DB
            database.upsert_papers(self.conn, unique_candidates)

            # Screen them
            pre_counts = database.count_papers(self.conn)
            self.screener.run_pass1(cfg)
            post_counts = database.count_papers(self.conn)

            new_included = post_counts["included"] - pre_counts["included"]
            yield_rate = new_included / len(unique_candidates) if unique_candidates else 0
            total_new_included += new_included

            self.log(
                f"Snowballing Agent: Round {round_num} — {new_included} new inclusions "
                f"(yield rate: {yield_rate:.1%})"
            )
            database.log_event(
                self.conn, "SNOWBALLING",
                f"Round {round_num}: {len(unique_candidates)} candidates, {new_included} included",
                {"yield_rate": yield_rate},
            )

            # Stopping criteria
            stop_reasons = []
            if new_included == 0:
                stop_reasons.append("no new papers found")
            if yield_rate < min_yield:
                stop_reasons.append(f"yield rate {yield_rate:.1%} < {min_yield:.1%}")
            if post_counts["included"] >= target_size * 1.5:
                stop_reasons.append("target corpus size exceeded")

            if stop_reasons:
                self.log(f"Snowballing Agent: stopping — {'; '.join(stop_reasons)}.")
                break

        self.log(f"Snowballing Agent: complete. {total_new_included} total new papers included.")
        return total_new_included

    def _get_all_known_ids(self) -> set[str]:
        all_papers = database.get_papers(self.conn)
        return {p["id"] for p in all_papers}
