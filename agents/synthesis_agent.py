"""Synthesis Agent — embeddings, clustering, narrative synthesis, gap analysis."""
from __future__ import annotations

import json
from typing import Callable

import numpy as np

from data import database
from utils import llm as llm_utils
from utils.prompts import (
    CLUSTER_LABEL_SYSTEM, CLUSTER_LABEL_USER,
    SYNTHESIS_SYSTEM, SYNTHESIS_USER,
)
import config


class SynthesisAgent:
    def __init__(
        self,
        api_key: str,
        db_conn,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.api_key = api_key
        self.conn = db_conn
        self.log = progress_callback or (lambda msg: None)

    def run(self, cfg: dict) -> dict:
        """
        Full synthesis pipeline:
        1. Compute embeddings
        2. Cluster papers
        3. Label clusters
        4. Generate per-cluster summaries
        5. Generate overall synthesis
        Returns the full synthesis dict.
        """
        papers = database.get_papers(self.conn, final_status="INCLUDED")
        if not papers:
            self.log("Synthesis Agent: no included papers.")
            return {}

        self.log(f"Synthesis Agent: starting synthesis for {len(papers)} papers…")

        # ── Step 1: Embeddings ─────────────────────────────────────────────────
        self.log("Synthesis Agent: computing embeddings…")
        texts = [
            f"{p.get('title', '')} {(p.get('abstract') or '')[:400]}"
            for p in papers
        ]
        try:
            vectors = llm_utils.get_embeddings(texts, self.api_key, config.EMBEDDING_MODEL)
            for p, vec in zip(papers, vectors):
                database.save_embeddings(self.conn, p["id"], vec)
        except Exception as e:
            self.log(f"Synthesis Agent: embedding failed — {e}. Skipping clustering.")
            vectors = []

        # ── Step 2: Clustering ─────────────────────────────────────────────────
        cluster_ids = self._cluster(papers, vectors)
        for p, cid in zip(papers, cluster_ids):
            database.update_paper(self.conn, p["id"], cluster_id=int(cid))

        n_clusters = len(set(c for c in cluster_ids if c >= 0))
        self.log(f"Synthesis Agent: identified {n_clusters} clusters.")

        # ── Step 3: Relevance scoring ──────────────────────────────────────────
        if vectors:
            from agents.relevance_agent import RelevanceAgent
            RelevanceAgent(self.api_key, self.conn, self.log).run(
                cfg.get("research_question", "")
            )

        # ── Step 5: 2D Projection for cluster map ─────────────────────────────
        coords_2d = self._project_2d(vectors)

        # ── Step 6: Label clusters and summarise ───────────────────────────────
        cluster_summaries: list[dict] = []
        unique_clusters = sorted(set(c for c in cluster_ids if c >= 0))

        for cid in unique_clusters:
            cluster_papers = [
                p for p, c in zip(papers, cluster_ids) if c == cid
            ]
            self.log(f"Synthesis Agent: labelling cluster {cid+1}/{n_clusters} ({len(cluster_papers)} papers)…")
            label_info = self._label_cluster(cluster_papers)

            label = label_info.get("label", f"Cluster {cid+1}")
            summary = label_info.get("summary", "")

            for p in cluster_papers:
                database.update_paper(self.conn, p["id"], cluster_label=label)

            cluster_summaries.append({
                "cluster_id": cid,
                "label": label,
                "n_papers": len(cluster_papers),
                "summary": summary,
            })

        # Papers with noise cluster (-1)
        noise_papers = [p for p, c in zip(papers, cluster_ids) if c == -1]
        if noise_papers:
            for p in noise_papers:
                database.update_paper(self.conn, p["id"], cluster_label="Uncategorised")

        # ── Step 5: Overall synthesis ──────────────────────────────────────────
        self.log("Synthesis Agent: generating overall narrative synthesis…")
        synthesis = self._overall_synthesis(cfg, papers, cluster_summaries)
        synthesis["cluster_summaries"] = cluster_summaries
        synthesis["n_papers"] = len(papers)
        synthesis["coords_2d"] = (
            [[float(x), float(y)] for x, y in coords_2d] if coords_2d is not None else []
        )
        synthesis["paper_ids"] = [p["id"] for p in papers]

        database.save_synthesis(self.conn, synthesis)
        database.log_event(self.conn, "SYNTHESIS", "Synthesis complete", {"n_clusters": n_clusters})
        self.log("Synthesis Agent: complete.")
        return synthesis

    # ── Private helpers ────────────────────────────────────────────────────────

    def _cluster(self, papers: list[dict], vectors: list[list[float]]) -> list[int]:
        """Cluster using HDBSCAN. Falls back to a single cluster if not enough data."""
        n = len(papers)
        if n < 4 or not vectors:
            return [0] * n

        try:
            import hdbscan
            X = np.array(vectors)
            min_cluster_size = max(2, n // 8)
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_cluster_size,
                metric="cosine",
                prediction_data=True,
            )
            labels = clusterer.fit_predict(X)
            # If everything is noise, fall back to k-means
            if all(l == -1 for l in labels):
                raise ValueError("all noise")
            return labels.tolist()
        except Exception:
            pass

        # Fallback: k-means with k=min(5, n//3)
        try:
            from sklearn.cluster import KMeans
            X = np.array(vectors)
            k = min(5, max(2, n // 3))
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            return km.fit_predict(X).tolist()
        except Exception:
            return [0] * n

    def _project_2d(self, vectors: list[list[float]]) -> list[tuple[float, float]] | None:
        if len(vectors) < 4:
            return None
        try:
            import umap
            X = np.array(vectors)
            reducer = umap.UMAP(n_components=2, random_state=42, n_neighbors=min(15, len(vectors)-1))
            coords = reducer.fit_transform(X)
            return [(float(r[0]), float(r[1])) for r in coords]
        except Exception:
            pass
        try:
            from sklearn.decomposition import PCA
            X = np.array(vectors)
            pca = PCA(n_components=2)
            coords = pca.fit_transform(X)
            return [(float(r[0]), float(r[1])) for r in coords]
        except Exception:
            return None

    def _label_cluster(self, papers: list[dict]) -> dict:
        papers_text = "\n\n".join([
            f"Title: {p.get('title','')}\nAbstract: {(p.get('abstract') or '')[:300]}"
            for p in papers[:15]
        ])
        try:
            return llm_utils.chat_completion_json(
                messages=[
                    {"role": "system", "content": CLUSTER_LABEL_SYSTEM},
                    {"role": "user", "content": CLUSTER_LABEL_USER.format(papers_text=papers_text)},
                ],
                model=config.SYNTHESIS_MODEL,
                api_key=self.api_key,
                temperature=0.4,
            )
        except Exception:
            return {"label": "Research cluster", "summary": ""}

    def _overall_synthesis(self, cfg: dict, papers: list[dict], cluster_summaries: list[dict]) -> dict:
        summaries_text = "\n\n".join([
            f"## {c['label']} ({c['n_papers']} papers)\n{c['summary']}"
            for c in cluster_summaries
        ])
        try:
            return llm_utils.chat_completion_json(
                messages=[
                    {"role": "system", "content": SYNTHESIS_SYSTEM},
                    {"role": "user", "content": SYNTHESIS_USER.format(
                        research_question=cfg.get("research_question", ""),
                        review_type=cfg.get("review_type", "systematic review"),
                        n_papers=len(papers),
                        cluster_summaries=summaries_text,
                    )},
                ],
                model=config.SYNTHESIS_MODEL,
                api_key=self.api_key,
                temperature=0.5,
                max_retries=2,
            )
        except Exception as e:
            self.log(f"Synthesis Agent: synthesis generation failed — {e}")
            return {
                "narrative_overview": "Synthesis generation failed.",
                "key_themes": [],
                "consensus_points": [],
                "key_debates": [],
                "research_gaps": [],
                "methodological_observations": "",
                "seminal_papers_notes": "",
            }
