"""Linkup response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Linkup `/v1/search` returns one of two JSON shapes depending on `outputType`:
- `searchResults`:  {"results": [{"name", "url", "content", ...}]}
- `sourcedAnswer`:  {"answer": "<text>", "sources": [{"name","url","snippet",...}]}

This module maps both into the shared, provider-agnostic `SearchResult`
shape and dedupes by URL.
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_search_results(raw_results: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map Linkup `searchResults` array → deduped list[SearchResult].

    Each item has at least `name`, `url`, and `content` (markdown). A trailing
    `type` field ("text"/"image") is tolerated. `max_results` bounds the list.
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        content = _clean(r.get("content"))
        out.append(
            SearchResult(
                title=_clean(r.get("name")),
                url=url,
                content=content,
                score=None,  # Linkup searchResults carries no relevance score
                raw_content=content or None,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def normalize_sources(sources: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map Linkup `sourcedAnswer` sources → deduped list[SearchResult].

    Each source has at least `name`, `url`, and `snippet` (a short excerpt).
    The snippet is used as the result content — full page text isn't included
    in `sourcedAnswer` responses.
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in sources or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = _clean(r.get("snippet"))
        out.append(
            SearchResult(
                title=_clean(r.get("name")),
                url=url,
                content=snippet,
                score=None,
                raw_content=snippet or None,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def _clean(v) -> str:
    """Coerce a value to a trimmed string (Linkup may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
