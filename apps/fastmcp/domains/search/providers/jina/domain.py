"""Jina response parsing — the Functional Core.

Per COELHO Nexus CODE-CONVENTIONS §4: no I/O, no async, no network, no
logging, no clocks, no mutable globals. Deterministic in / out.

Jina's `s.jina.ai` search returns PLAIN-TEXT markdown (not JSON). The body is
a sequence of numbered result blocks:

    [1] Title: ...          <- optional, may be empty
    [1] URL Source: https://...
    [1] Description: ...    <- optional, may be empty
    [1] Date: ...           <- optional
    <full page markdown until the next [N] block or EOF>

This module parses that text into the shared, provider-agnostic
`SearchResult` shape. Blocks are detected by a line matching `[N] Title|URL
Source|Description|Date:` where N is the block index. Content for a block is
everything between its header lines and the next `[N+1]` header.
"""
from __future__ import annotations

import re

from ...schemas import SearchResult


# A block header line, capturing index + field + value.
# e.g. "[3] URL Source: https://..." -> ("3", "URL Source", "https://...")
_BLOCK_LINE = re.compile(r"^\[(\d+)\]\s*(Title|URL Source|Description|Date):\s?(.*)$")


def parse_results(text: str, max_results: int | None = None) -> list[SearchResult]:
    """Parse s.jina.ai markdown output → list of SearchResult.

    `text` is the raw plain-text body returned by the endpoint. Each numbered
    block yields one SearchResult. `max_results` bounds the returned list
    (None = keep all). Deterministic; malformed input degrades to fewer/no
    results rather than raising.
    """
    if not text:
        return []

    headers_by_block: dict[str, dict[str, str]] = {}
    order: list[str] = []

    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _BLOCK_LINE.match(line)
        if not m:
            continue
        idx, field, value = m.group(1), m.group(2), m.group(3).strip()
        if idx not in headers_by_block:
            headers_by_block[idx] = {}
            order.append(idx)
        headers_by_block[idx][field] = value

    # Assign content: for each block, content = lines between its LAST header
    # line and the first header line of the NEXT block (or EOF).
    # Track the line index of the last header of each block.
    last_header_line: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _BLOCK_LINE.match(line)
        if m:
            last_header_line[m.group(1)] = i

    # Content boundaries: next block's first header line after this block's
    # last header line.
    first_header_line: dict[str, int] = {}
    for idx in order:
        if idx in last_header_line:
            first_header_line[idx] = last_header_line[idx]

    content: dict[str, str] = {}
    for n, idx in enumerate(order):
        start = last_header_line.get(idx)
        if start is None:
            continue
        # next block start = its first header line; find min header line > start
        nxt_lines = [
            ln for other, ln in last_header_line.items()
            if other != idx and ln > start
        ]
        end = min(nxt_lines) if nxt_lines else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        content[idx] = body

    results: list[SearchResult] = []
    seen: set[str] = set()
    for idx in order:
        h = headers_by_block[idx]
        url = (h.get("URL Source") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (h.get("Title") or "").strip()
        desc = (h.get("Description") or "").strip()
        body = (content.get(idx) or "").strip()
        # Jina scrapes the RENDERED page, so `body` is full page markdown full of
        # chrome (cookie walls, login/blocked notices, nav) rather than a clean
        # snippet. The `Description` field (when present) is the curated snippet —
        # prefer it for `content`; fall back to the body only when no description
        # is provided. The fuller body is still exposed as `raw_content` for deep
        # context on demand.
        snippet = body or desc  # unchanged fallback when body only
        page_content = desc or body  # prefer the curated description
        results.append(
            SearchResult(
                title=title,
                url=url,
                content=page_content,
                score=None,  # Jina search provides no relevance score
                raw_content=(snippet if snippet != page_content else None),
            )
        )

    if max_results is not None and max_results > 0:
        results = results[:max_results]
    return results
