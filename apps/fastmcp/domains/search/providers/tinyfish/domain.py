"""TinyFish response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

TinyFish `GET /` (root) returns:
  {
    "query": "...",
    "results": [
      {"position": 1, "site_name": "en.wikipedia.org", "title": "...",
       "snippet": "...", "url": "...", "date": "...?"},
      ...
    ],
    "total_results": N,
    "page": 0
  }

There is no LLM-synthesized answer field (pure search index), so
`normalize_answer` always returns None — the router simply falls back to
other providers when an answer is requested.
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_results(data: dict | None, max_results: int | None = None) -> list[SearchResult]:
    """Map TinyFish `results[]` → deduped list[SearchResult].

    Items without a `url` are skipped. `max_results` bounds the list but never
    returns fewer unique URLs than the provider sent when capped.
    """
    results: list[dict] = [r for r in ((data or {}).get("results") or []) if isinstance(r, dict)]
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            SearchResult(
                title=_clean(r.get("title")),
                url=url,
                content=_clean(r.get("snippet")),
                score=None,  # TinyFish returns position, not a relevance score
                raw_content=None,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def normalize_answer(data) -> str | None:
    """TinyFish returns no answer payload — always None.

    Exists to satisfy the uniform provider surface so the caller can treat
    every provider identically.
    """
    return None


def _clean(v) -> str:
    """Coerce a value to a trimmed string (TinyFish may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
