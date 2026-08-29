"""You.com response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

You.com `/v1/search` returns a top-level `results` object with typed
sections. The usable one is `web`, an array of result dicts carrying at
least `title`, `url`, and `snippets` (a list of short excerpts); a `news`
section may also be present with the same shape. This module maps `web`
(and `news`, when `web` is empty) into the shared, provider-agnostic
`SearchResult` shape and dedupes by URL.
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_web(raw_results: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map You.com `results.web` array → deduped list[SearchResult].

    Each item carries at least `title`, `url`, and `snippets` (a list of
    strings). The snippets are joined into the result content. `description`
    and `page_age` are tolerated. `max_results` bounds the list.
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
        content = _snippet_text(r.get("snippets")) or _clean(r.get("description"))
        out.append(
            SearchResult(
                title=_clean(r.get("title")),
                url=url,
                content=content,
                score=None,  # You.com search carries no relevance score
                raw_content=content or None,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def normalize_news(raw_results: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map You.com `results.news` array → deduped list[SearchResult].

    Identical shape to `web`; used as a fallback when no `web` results are
    returned for the query.
    """
    return normalize_web(raw_results, max_results=max_results)


def _snippet_text(snippets) -> str:
    """Join a `snippets` list of strings (or a single string) into text."""
    if snippets is None:
        return ""
    if isinstance(snippets, str):
        return snippets.strip()
    if isinstance(snippets, list):
        parts = [str(s).strip() for s in snippets if str(s).strip()]
        return "\n".join(parts)
    return ""


def _clean(v) -> str:
    """Coerce a value to a trimmed string (You.com may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
