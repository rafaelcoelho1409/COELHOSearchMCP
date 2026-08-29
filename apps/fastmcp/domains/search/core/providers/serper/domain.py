"""Serper response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Serper `POST /search` returns a top-level JSON object with an `organic[]`
array of Google organic results. Each item carries at least `title`, `link`,
`position`, and `snippet` (optioanlly `date`/`datePosted`/`richSnippet`). An
`answerBox` (direct answer) may also be present. This module maps `organic[]`
into the shared, provider-agnostic `SearchResult` shape and dedupes by URL,
falling back to the Google trueview/knowledge-graph-style snippets when
`organic` is empty.
"""
from __future__ import annotations

from ....schemas import SearchResult


def normalize_organic(raw_results: list[dict], max_results: int | None = None) -> list[SearchResult]:
    """Map Serper `organic` array → deduped list[SearchResult].

    Each item carries `title`, `link`, `snippet`, and `position`. The snippet
    is used as the result content. `max_results` bounds the list. Items without
    a `link` are skipped (a SERP may include non-URL entries).
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("link") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        content = _clean(r.get("snippet")) or _clean(r.get("title"))
        out.append(
            SearchResult(
                title=_clean(r.get("title")),
                url=url,
                content=content,
                score=None,  # Serper organic results carry no relevance score
                raw_content=content or None,
            )
        )
    if max_results is not None and max_results > 0:
        out = out[:max_results]
    return out


def normalize_answer(answer_box: dict | None) -> str | None:
    """Extract the direct-answer text from Serper's `answerBox`, if present.

    Google's answer box carries `answer` (or `snippet`) plus `title` and
    `link`. Returns a null-safe string or None when there's no usable answer.
    """
    if not isinstance(answer_box, dict):
        return None
    text = (
        _clean(answer_box.get("answer"))
        or _clean(answer_box.get("snippet"))
        or _clean(answer_box.get("title"))
    )
    return text or None


def _clean(v) -> str:
    """Coerce a value to a trimmed string (Serper may return None/empty)."""
    if not v:
        return ""
    return str(v).strip()
