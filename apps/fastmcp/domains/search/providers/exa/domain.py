"""Exa response normalization — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Exa `/search` returns `results` as a list of dicts, each carrying `id`,
`title`, `url`, `publishedDate`/`author` (optional), and per-request
`contents` blocks with `text`, `highlights`, and/or `summary`. This module
maps those into the shared, provider-agnostic `SearchResult` shape and
dedupes by URL.
"""
from __future__ import annotations

from ...schemas import SearchResult


def normalize_results(raw_results: list[dict]) -> list[SearchResult]:
    """Map Exa's raw result dicts → deduped list[SearchResult].

    Each Exa result dict carries at least `id`, `title`, `url`, and (when
    requested) the fetched page text. In practice Exa returns the text as a
    TOP-LEVEL `text` key (requested text is flattened into result objects),
    not nested under `contents`. For compatibility we accept text from either
    a top-level `text` field or a nested `contents.text` / `contents.summary`,
    tolerating missing/unknown keys. Exa deprecated `score` in auto search,
    so we leave `score` as None.
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
        text = _extract_text(r)
        out.append(
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=url,
                content=text,
                score=None,  # Exa deprecated score in auto search
                raw_content=text or None,
            )
        )
    return out


def _extract_text(result: dict) -> str:
    """Pull the fetched page text from an Exa result.

    Exa returns requested text as a top-level `text` key; some SDK/config
    shapes emit it nested under `contents` (e.g. `contents.text` or a
    `contents.summary`). Prefer the top-level `text`, then the nested
    variants.
    """
    top = result.get("text")
    if isinstance(top, str) and top.strip():
        return top.strip()

    contents = result.get("contents")
    if isinstance(contents, dict):
        for key in ("text", "summary", "highlights"):
            v = contents.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list):  # highlights may be a string list
                joined = " ".join(x for x in v if isinstance(x, str) and x.strip())
                if joined.strip():
                    return joined.strip()
    return ""


def _clean_text(v) -> str:
    """Coerce an Exa text field to a trimmed string (Exa may return None)."""
    if not v:
        return ""
    return str(v).strip()
