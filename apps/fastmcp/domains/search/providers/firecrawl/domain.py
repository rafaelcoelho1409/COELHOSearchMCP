"""Firecrawl response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Firecrawl `POST /v1/search` returns `{"success": true, "data": [...]}`, where
each entry carries at least `url`, `title`, and `description`. The description
is LLM-ready markdown (full page content), already the richest available text,
so we use it directly as the result content. There is no relevance score and
no native direct-answer field in the search response.
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_results(data: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map Firecrawl `data` array → deduped list[SearchResult].

    Each entry carries `url`, `title`, and `description` (markdown). The
    description becomes the result content. `score` is None (Firecrawl search
    exposes no relevance score). Items without a `url` are skipped (`description`
    only entries are not linkable results). `max_results` bounds the list.
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in data or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        content = _clean(r.get("description"))
        out.append(
            SearchResult(
                title=_clean(r.get("title")),
                url=url,
                content=content,
                score=None,  # Firecrawl search carries no relevance score
                raw_content=None,  # description IS the full text; no separate raw
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def _clean(v) -> str:
    """Coerce a value to a trimmed string (Firecrawl may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
