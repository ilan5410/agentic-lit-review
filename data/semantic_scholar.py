"""Semantic Scholar API client."""
from __future__ import annotations

import time
import hashlib

import httpx

from config import SEMANTIC_SCHOLAR_BASE

FIELDS = (
    "paperId,externalIds,title,abstract,authors,year,venue,"
    "citationCount,fieldsOfStudy,tldr,openAccessPdf,references"
)


def _headers(api_key: str) -> dict:
    h = {"User-Agent": "LitReviewApp/1.0"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def _rate_limit(api_key: str) -> float:
    return 0.12 if api_key else 1.1  # seconds between requests


def _parse_paper(p: dict, query_source: str = "") -> dict | None:
    title = p.get("title")
    if not title:
        return None

    ss_id = p.get("paperId", "")
    ext = p.get("externalIds", {}) or {}
    doi = ext.get("DOI", "")
    paper_id = doi or ss_id or hashlib.md5(title.encode()).hexdigest()

    abstract = p.get("abstract") or ""
    tldr = (p.get("tldr") or {}).get("text", "")
    if not abstract and tldr:
        abstract = tldr

    authors = [
        {"name": a.get("name", ""), "orcid": ""}
        for a in (p.get("authors") or [])[:20]
    ]

    oa_pdf = (p.get("openAccessPdf") or {}).get("url", "")
    refs = [
        r.get("paperId") for r in (p.get("references") or []) if r.get("paperId")
    ]

    return {
        "id": paper_id,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": p.get("year"),
        "journal": p.get("venue") or "",
        "source": "semantic_scholar",
        "document_type": "article",
        "citation_count": p.get("citationCount") or 0,
        "open_access_url": oa_pdf,
        "concepts": [],
        "openalex_id": None,
        "semantic_scholar_id": ss_id,
        "referenced_works": refs,
        "query_source": query_source,
    }


def search_papers(
    query: str,
    api_key: str,
    *,
    fields_of_study: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_results: int = 100,
    query_source: str = "",
    progress_callback=None,
) -> list[dict]:
    """Search Semantic Scholar. Returns normalised paper dicts."""
    params: dict = {
        "query": query,
        "fields": FIELDS,
        "limit": 100,
        "offset": 0,
    }
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)
    if year_min and year_max:
        params["year"] = f"{year_min}-{year_max}"
    elif year_min:
        params["year"] = f"{year_min}-"
    elif year_max:
        params["year"] = f"-{year_max}"

    papers: list[dict] = []
    client = httpx.Client(timeout=30)
    sleep = _rate_limit(api_key)

    try:
        while len(papers) < max_results:
            resp = client.get(
                f"{SEMANTIC_SCHOLAR_BASE}/paper/search",
                params=params,
                headers=_headers(api_key),
            )
            if resp.status_code == 429:
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json()

            for p in data.get("data", []):
                parsed = _parse_paper(p, query_source)
                if parsed:
                    papers.append(parsed)
                if len(papers) >= max_results:
                    break

            total = data.get("total", 0)
            params["offset"] += params["limit"]
            if params["offset"] >= min(total, max_results):
                break

            if progress_callback:
                progress_callback(f"Semantic Scholar: retrieved {len(papers)} papers…")
            time.sleep(sleep)
    finally:
        client.close()

    return papers


def get_paper(paper_id: str, api_key: str) -> dict | None:
    """Fetch a single paper by Semantic Scholar ID."""
    try:
        client = httpx.Client(timeout=30)
        resp = client.get(
            f"{SEMANTIC_SCHOLAR_BASE}/paper/{paper_id}",
            params={"fields": FIELDS},
            headers=_headers(api_key),
        )
        client.close()
        if resp.status_code == 200:
            return _parse_paper(resp.json())
    except Exception:
        pass
    return None
