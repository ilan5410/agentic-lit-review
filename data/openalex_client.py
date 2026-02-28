"""OpenAlex API client with pagination, abstract reconstruction, and snowballing."""
from __future__ import annotations

import re
import time
import hashlib
from typing import Iterator

import httpx

from config import OPENALEX_BASE


def _sanitize_query(query: str) -> str:
    """
    Strip any field-prefix syntax the LLM might generate (title.search:X,
    abstract.search:X, concepts.id:X, host_venue.type:X, publication_year:X)
    and collapse boolean operators, leaving plain searchable keywords.
    The OpenAlex ?search= parameter only accepts plain text.
    """
    # For content fields (title/abstract.search, concepts.id): keep the VALUE, drop the prefix.
    cleaned = re.sub(r'\b(?:title|abstract|fulltext)\.search:(\S+)', r'\1', query)
    cleaned = re.sub(r'\b(?:concepts|topics)\.id:(\S+)', r'\1', cleaned)
    # For structural filter fields: drop both key and value (not useful as search terms).
    cleaned = re.sub(
        r'\b(?:publication_year|host_venue(?:\.\w+)*|type|language|open_access(?:\.\w+)*):\S+',
        '', cleaned,
    )
    # Drop any remaining field.field:value patterns (keep value).
    cleaned = re.sub(r'\b\w+(?:\.\w+)+:(\S+)', r'\1', cleaned)
    # Drop bare word:value patterns.
    cleaned = re.sub(r'\b\w+:\S+', '', cleaned)
    # Drop year ranges and standalone 4-digit years (already encoded in the filter param).
    cleaned = re.sub(r'\b\d{4}(?:-\d{4})?\b', '', cleaned)
    # Remove boolean operators and grouping punctuation.
    cleaned = re.sub(r'\b(AND|OR|NOT)\b', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[()"\[\]]', ' ', cleaned)
    # Tokens that are OpenAlex enum values, not meaningful search terms.
    _SKIP = {'journal_article', 'journal', 'article', 'preprint', 'book_chapter', 'review'}
    # Deduplicate, preserve order.
    seen: set[str] = set()
    words: list[str] = []
    for w in cleaned.split():
        lw = w.lower().strip('.,;:-')
        if lw and len(lw) > 2 and lw not in seen and lw not in _SKIP:
            seen.add(lw)
            words.append(lw)
    return ' '.join(words[:12])  # cap at 12 terms


def _headers(email: str) -> dict:
    h = {"User-Agent": f"LitReviewApp/1.0 (mailto:{email})"}
    if email:
        h["mailto"] = email
    return h


def reconstruct_abstract(inverted_index: dict | None) -> str:
    """Convert OpenAlex inverted-index abstract to plain text."""
    if not inverted_index:
        return ""
    try:
        positions: list[tuple[int, str]] = []
        for word, locs in inverted_index.items():
            for pos in locs:
                positions.append((pos, word))
        positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in positions)
    except Exception:
        return ""


def _parse_work(w: dict, query_source: str = "") -> dict | None:
    title = w.get("title")
    if not title:
        return None
    oa_id = w.get("id", "")
    doi = w.get("doi", "")
    paper_id = doi or oa_id or hashlib.md5(title.encode()).hexdigest()

    abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
    authors = [
        {
            "name": a.get("author", {}).get("display_name", ""),
            "orcid": a.get("author", {}).get("orcid", ""),
        }
        for a in w.get("authorships", [])[:20]
    ]
    concepts = [
        {"name": c.get("display_name", ""), "score": c.get("score", 0)}
        for c in w.get("concepts", [])[:10]
    ]

    pub_year = w.get("publication_year")
    venue = w.get("primary_location", {}) or {}
    source = venue.get("source", {}) or {}
    journal = source.get("display_name", "")

    oa_location = w.get("open_access", {}) or {}
    oa_url = oa_location.get("oa_url", "")

    doc_type = w.get("type", "article")
    ref_works = [r for r in (w.get("referenced_works") or []) if r]

    return {
        "id": paper_id,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": pub_year,
        "journal": journal,
        "source": "openalex",
        "document_type": doc_type,
        "citation_count": w.get("cited_by_count", 0) or 0,
        "open_access_url": oa_url,
        "concepts": concepts,
        "openalex_id": oa_id,
        "semantic_scholar_id": None,
        "referenced_works": ref_works,
        "query_source": query_source,
    }


def search_works(
    query: str,
    email: str,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    doc_types: list[str] | None = None,
    max_results: int = 200,
    query_source: str = "",
    progress_callback=None,
) -> list[dict]:
    """Search OpenAlex works. Returns list of normalised paper dicts."""
    clean = _sanitize_query(query)
    if clean != query:
        if progress_callback:
            progress_callback(f"OpenAlex: sanitized query → '{clean}'")
    params: dict = {
        "search": clean,
        "select": (
            "id,doi,title,abstract_inverted_index,authorships,publication_year,"
            "primary_location,open_access,type,cited_by_count,concepts,referenced_works"
        ),
        "per-page": 50,
    }
    if email:
        params["mailto"] = email

    filters = []
    if year_min:
        filters.append(f"publication_year:>{year_min - 1}")
    if year_max:
        filters.append(f"publication_year:<{year_max + 1}")
    if doc_types:
        type_str = "|".join(doc_types)
        filters.append(f"type:{type_str}")
    if filters:
        params["filter"] = ",".join(filters)

    papers: list[dict] = []
    cursor = "*"
    client = httpx.Client(timeout=30)

    try:
        while len(papers) < max_results:
            params["cursor"] = cursor
            resp = client.get(f"{OPENALEX_BASE}/works", params=params, headers=_headers(email))
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                break

            for w in results:
                parsed = _parse_work(w, query_source)
                if parsed:
                    papers.append(parsed)
                if len(papers) >= max_results:
                    break

            meta = data.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break

            if progress_callback:
                progress_callback(f"OpenAlex: retrieved {len(papers)} papers…")
            time.sleep(0.12)  # ~8 req/sec, polite pool limit is 10/sec
    finally:
        client.close()

    return papers


def get_paper(openalex_id: str, email: str) -> dict | None:
    """Fetch a single work by OpenAlex ID."""
    try:
        client = httpx.Client(timeout=30)
        params = {"mailto": email} if email else {}
        resp = client.get(f"{OPENALEX_BASE}/works/{openalex_id}", params=params, headers=_headers(email))
        client.close()
        if resp.status_code == 200:
            return _parse_work(resp.json())
    except Exception:
        pass
    return None


def get_references(openalex_id: str, email: str, max_results: int = 500) -> list[dict]:
    """Fetch works referenced by this paper (backward snowballing)."""
    try:
        params: dict = {
            "filter": f"cites:{openalex_id}",
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,primary_location,open_access,type,cited_by_count,concepts,referenced_works",
            "per-page": 50,
        }
        if email:
            params["mailto"] = email
        return _paginate(params, email, max_results)
    except Exception:
        return []


def get_citing_papers(openalex_id: str, email: str, max_results: int = 500) -> list[dict]:
    """Fetch works that cite this paper (forward snowballing)."""
    try:
        params: dict = {
            "filter": f"cited_by:{openalex_id}",
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,primary_location,open_access,type,cited_by_count,concepts,referenced_works",
            "per-page": 50,
        }
        if email:
            params["mailto"] = email
        return _paginate(params, email, max_results)
    except Exception:
        return []


def _paginate(params: dict, email: str, max_results: int) -> list[dict]:
    papers: list[dict] = []
    cursor = "*"
    client = httpx.Client(timeout=30)
    try:
        while len(papers) < max_results:
            params["cursor"] = cursor
            resp = client.get(f"{OPENALEX_BASE}/works", params=params, headers=_headers(email))
            resp.raise_for_status()
            data = resp.json()
            for w in data.get("results", []):
                parsed = _parse_work(w)
                if parsed:
                    papers.append(parsed)
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor or not data.get("results"):
                break
            time.sleep(0.12)
    finally:
        client.close()
    return papers
