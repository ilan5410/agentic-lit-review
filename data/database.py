"""DuckDB schema, connection management, and CRUD operations."""
from __future__ import annotations

import json
import tempfile
import os
from datetime import datetime
from typing import Any

import duckdb


# ── Connection ─────────────────────────────────────────────────────────────────

def get_db_path(session_id: str) -> str:
    """Return a per-session DuckDB file path (in the system temp dir)."""
    tmp = tempfile.gettempdir()
    return os.path.join(tmp, f"litreview_{session_id}.duckdb")


def get_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    """Open (or reuse) a DuckDB connection and ensure schema exists."""
    conn = duckdb.connect(db_path)
    _init_schema(conn)
    return conn


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id VARCHAR PRIMARY KEY,
            doi VARCHAR,
            title VARCHAR NOT NULL,
            abstract TEXT,
            authors JSON,
            year INTEGER,
            journal VARCHAR,
            source VARCHAR,
            document_type VARCHAR,
            citation_count INTEGER,
            open_access_url VARCHAR,
            concepts JSON,
            openalex_id VARCHAR,
            semantic_scholar_id VARCHAR,
            referenced_works JSON,

            -- Pipeline fields
            query_source VARCHAR,
            screening_pass1 VARCHAR,
            screening_pass1_reason TEXT,
            screening_pass1_confidence FLOAT,
            screening_pass2 VARCHAR,
            screening_pass2_reason TEXT,
            human_decision VARCHAR,
            quality_score FLOAT,
            quality_notes TEXT,
            quality_flag VARCHAR,
            relevance_score FLOAT,
            cluster_id INTEGER,
            cluster_label VARCHAR,
            final_status VARCHAR,
            found_via VARCHAR DEFAULT 'search',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            paper_id VARCHAR PRIMARY KEY,
            vector FLOAT[]
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_queries (
            id INTEGER PRIMARY KEY,
            query_text VARCHAR,
            target_api VARCHAR,
            results_count INTEGER,
            executed_at TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id INTEGER PRIMARY KEY,
            stage VARCHAR,
            message TEXT,
            details JSON,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            research_question TEXT,
            review_type VARCHAR,
            strictness INTEGER,
            inclusion_criteria TEXT,
            exclusion_criteria TEXT,
            year_min INTEGER,
            year_max INTEGER,
            target_corpus_size INTEGER,
            config_json JSON
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS generated_queries (
            id INTEGER PRIMARY KEY,
            api VARCHAR,
            query_text VARCHAR,
            description VARCHAR
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS synthesis_result (
            id INTEGER PRIMARY KEY DEFAULT 1,
            result_json JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


# ── Papers ─────────────────────────────────────────────────────────────────────

def upsert_papers(conn: duckdb.DuckDBPyConnection, papers: list[dict]) -> int:
    """Insert papers, skipping duplicates by id. Returns count inserted."""
    if not papers:
        return 0
    inserted = 0
    for p in papers:
        existing = conn.execute(
            "SELECT id FROM papers WHERE id = ?", [p["id"]]
        ).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT INTO papers (
                id, doi, title, abstract, authors, year, journal, source,
                document_type, citation_count, open_access_url, concepts,
                openalex_id, semantic_scholar_id, referenced_works, query_source, found_via
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            p.get("id"), p.get("doi"), p.get("title"), p.get("abstract"),
            json.dumps(p.get("authors", [])), p.get("year"), p.get("journal"),
            p.get("source"), p.get("document_type"), p.get("citation_count"),
            p.get("open_access_url"), json.dumps(p.get("concepts", [])),
            p.get("openalex_id"), p.get("semantic_scholar_id"),
            json.dumps(p.get("referenced_works", [])),
            p.get("query_source"), p.get("found_via", "search"),
        ])
        inserted += 1
    return inserted


def update_paper(conn: duckdb.DuckDBPyConnection, paper_id: str, **fields) -> None:
    """Update arbitrary fields on a paper row."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [paper_id]
    conn.execute(f"UPDATE papers SET {set_clause} WHERE id = ?", values)


def get_papers(
    conn: duckdb.DuckDBPyConnection,
    *,
    status: str | None = None,
    final_status: str | None = None,
    pass1: str | None = None,
) -> list[dict]:
    """Fetch papers with optional status filters."""
    clauses = []
    params = []
    if status is not None:
        clauses.append("final_status = ?")
        params.append(status)
    if final_status is not None:
        clauses.append("final_status = ?")
        params.append(final_status)
    if pass1 is not None:
        clauses.append("screening_pass1 = ?")
        params.append(pass1)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM papers {where} ORDER BY citation_count DESC NULLS LAST",
        params,
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def count_papers(conn: duckdb.DuckDBPyConnection, **filters) -> dict[str, int]:
    """Return counts broken down by pipeline stage."""
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    included = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE final_status = 'INCLUDED'"
    ).fetchone()[0]
    excluded = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE final_status = 'EXCLUDED'"
    ).fetchone()[0]
    borderline = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE screening_pass1 = 'BORDERLINE' AND human_decision IS NULL"
    ).fetchone()[0]
    return {
        "total": total,
        "included": included,
        "excluded": excluded,
        "borderline": borderline,
        "unscreened": total - included - excluded - borderline,
    }


# ── Embeddings ─────────────────────────────────────────────────────────────────

def save_embeddings(conn: duckdb.DuckDBPyConnection, paper_id: str, vector: list[float]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (paper_id, vector) VALUES (?, ?)",
        [paper_id, vector],
    )


def get_embeddings(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, list[float]]]:
    rows = conn.execute("SELECT paper_id, vector FROM embeddings").fetchall()
    return [(r[0], r[1]) for r in rows]


# ── Pipeline Log ───────────────────────────────────────────────────────────────

def log_event(conn: duckdb.DuckDBPyConnection, stage: str, message: str, details: dict | None = None) -> None:
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM pipeline_log").fetchone()[0]
    conn.execute(
        "INSERT INTO pipeline_log (id, stage, message, details) VALUES (?, ?, ?, ?)",
        [next_id, stage, message, json.dumps(details or {})],
    )


def get_log(conn: duckdb.DuckDBPyConnection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT stage, message, details, ts FROM pipeline_log ORDER BY id DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [
        {"stage": r[0], "message": r[1], "details": json.loads(r[2] or "{}"), "ts": r[3]}
        for r in rows
    ]


# ── Config ─────────────────────────────────────────────────────────────────────

def save_config(conn: duckdb.DuckDBPyConnection, cfg: dict) -> None:
    conn.execute("DELETE FROM review_config")
    conn.execute("""
        INSERT INTO review_config (
            id, research_question, review_type, strictness, inclusion_criteria,
            exclusion_criteria, year_min, year_max, target_corpus_size, config_json
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        cfg.get("research_question"), cfg.get("review_type"), cfg.get("strictness"),
        cfg.get("inclusion_criteria"), cfg.get("exclusion_criteria"),
        cfg.get("year_min"), cfg.get("year_max"), cfg.get("target_corpus_size"),
        json.dumps(cfg),
    ])


def get_config(conn: duckdb.DuckDBPyConnection) -> dict:
    row = conn.execute("SELECT config_json FROM review_config WHERE id = 1").fetchone()
    if row:
        return json.loads(row[0] or "{}")
    return {}


# ── Generated Queries ──────────────────────────────────────────────────────────

def save_queries(conn: duckdb.DuckDBPyConnection, queries: list[dict]) -> None:
    conn.execute("DELETE FROM generated_queries")
    for i, q in enumerate(queries):
        conn.execute(
            "INSERT INTO generated_queries (id, api, query_text, description) VALUES (?, ?, ?, ?)",
            [i, q["api"], q["query_text"], q.get("description", "")],
        )


def get_queries(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute("SELECT api, query_text, description FROM generated_queries").fetchall()
    return [{"api": r[0], "query_text": r[1], "description": r[2]} for r in rows]


# ── Synthesis ──────────────────────────────────────────────────────────────────

def save_synthesis(conn: duckdb.DuckDBPyConnection, result: dict) -> None:
    conn.execute("DELETE FROM synthesis_result")
    conn.execute(
        "INSERT INTO synthesis_result (id, result_json) VALUES (1, ?)",
        [json.dumps(result)],
    )


def get_synthesis(conn: duckdb.DuckDBPyConnection) -> dict | None:
    row = conn.execute("SELECT result_json FROM synthesis_result WHERE id = 1").fetchone()
    if row:
        return json.loads(row[0])
    return None
