"""Tavily response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

The official `tavily-python` SDK returns raw dicts from its `.search()`.
This module maps those dicts into the shared, provider-agnostic
`SearchResult` shape and dedupes by URL (Tavily docs recommend deduping to
save tokens and avoid repetitive context).
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_results(raw_results: list[dict]) -> list[SearchResult]:
    """Map Tavily's raw result dicts → deduped list[SearchResult].

    Each Tavily result dict carries at least `title`, `url`, `content`, and
    `score` (0-1); `raw_content` only when requested. Unknown/missing keys are
    tolerated and defaulted.
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
        out.append(
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=url,
                content=(r.get("content") or "").strip(),
                score=_as_float(r.get("score")),
                raw_content=r.get("raw_content") if r.get("raw_content") is not None else None,
            )
        )
    return out


def _as_float(v) -> float | None:
    """Tavily may return score as a float or a numeric string; coerce safely."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
