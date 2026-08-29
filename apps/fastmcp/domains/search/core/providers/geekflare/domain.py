"""Geekflare response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Geekflare `POST /search` returns:
  {
    "timestamp": ...,
    "apiStatus": "success",
    "apiCode": 200,
    "meta": {"query": "...", "count": N, ...},
    "data": [
      {"title": "...", "url": "...", "snippet": "...", "position": 1,
       "date": "...", "content": "<full article when scrape: true>"},
      ...
    ]
  }

With `groundedAnswer: true`, `data` becomes an object instead:
  {
    "data": {
      "answer": "<LLM-synthesized answer>",
      "sources": [{"title": "...", "url": "...", "position": 1}, ...]
    }
  }
"""
from __future__ import annotations

from ....schemas import SearchResult


def normalize_results(data: list[dict] | dict | None, max_results: int | None = None) -> list[SearchResult]:
    """Map Geekflare `data` → deduped list[SearchResult].

    Two shapes are possible:
      * list — a plain web search: `[{title,url,snippet,position,content?}, ...]`
      * dict — a grounded-answer search: `{answer, sources:[{title,url,position}]}`;
        in that case the `sources` array is mapped to results so the caller
        doesn't lose the cited links alongside the answer.

    Items without a `url` are skipped. `max_results` bounds the list but never
    returns fewer unique URLs than the provider sent when capped.
    """
    if isinstance(data, dict):
        data = data.get("sources") or []
    results: list[dict] = [r for r in (data or []) if isinstance(r, dict)]
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        content = _clean(r.get("snippet"))
        raw = _clean(r.get("content")) or None
        out.append(
            SearchResult(
                title=_clean(r.get("title")),
                url=url,
                content=content,
                score=None,  # Geekflare returns position, not a relevance score
                raw_content=raw,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def normalize_answer(data) -> str | None:
    """Extract Geekflare's grounded answer when `groundedAnswer: true`.

    In that mode `data` is a dict `{"answer": "...", "sources": [...]}` rather
    than a list. Returns the answer string or None when not present.
    """
    if not isinstance(data, dict):
        return None
    text = _clean(data.get("answer"))
    return text or None


def _clean(v) -> str:
    """Coerce a value to a trimmed string (Geekflare may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
