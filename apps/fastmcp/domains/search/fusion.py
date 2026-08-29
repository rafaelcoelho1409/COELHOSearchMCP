"""Result-quality pooling — normalization, dedup, and RRF fusion (the Functional Core).

Per COELHO Nexus CODE-CONVENTIONS §4: this module is pure / deterministic —
no I/O, no async, no network, no logging, no clocks, no mutable globals.

This is the SOTA "great pool of quality results" layer on top of the FGTS-VA
router (see docs/ROUTING.md §7). Providers return heterogeneous results
(varying `content` length, raw vs snippet, incompatible `score` scales). This
module normalizes them to a consistent shape, dedupes the same URL across
providers, and — on the quality ensemble path — fuses several ranked lists
with Reciprocal Rank Fusion (RRF, k=60) exactly as the 2026 SOTA prescribes
(score-agnostic, no training/weights, handles partial overlap gracefully).

It also produces two cheap, self-supervised quality signals the bandit reward
consumes:
  - **tidiness**: how compact / token-efficient a provider's result content is
    (penalizes raw-page-dump bloat without any LLM judge).
  - **fusion-survival agreement**: how many of a provider's results survived
    RRF into the final top-k (a downstream, consensus-relevance quality label).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .schemas import SearchResult


# Default content cap (characters). Providers that dump full page bodies
# (e.g. Firecrawl raw markdown) are truncated here so LLM-facing `content` is
# consistent across every provider.
CONTENT_CAP_CHARS = 500

# Optional raw-content cap (characters). `raw_content` is the provider's full
# page body; bounding it keeps responses token-efficient (live testing showed
# ~98KB across 5 results otherwise) while still exposing deeper text on demand.
RAW_CAP_CHARS = 2000

# RRF constant (k=60 the 2026 standard). Lower → top ranks weigh more.
RRF_K = 60.0


def canonicalize_url(url: str) -> str:
    """Return a canonical URL so the same page is comparable across providers.

    Strips the fragment, removes common tracking params (utm_*, fbclid, gclid),
    lowercases the scheme/host, and drops default ports. Deterministic and lossy
    on purpose — this is a dedup key, not a redirect resolver.
    """
    if not url or not url.strip():
        return ""
    try:
        parts = urlsplit(url.strip())
    except (ValueError, TypeError):
        return url.strip()
    scheme = (parts.scheme or "").lower()
    netloc = parts.netloc.lower()
    host = netloc
    if ":" in netloc and netloc.rsplit(":", 1)[-1].isdigit():
        host, port = netloc.rsplit(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host
    query = _strip_tracking(parts.query)
    # Drop trailing slash on the path so `<page>` and `<page>/` collapse.
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    clean = urlunsplit((scheme, netloc, path, query, ""))
    return clean


_TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "gclsrc", "dclid", "igshid", "mc_cid", "mc_eid",
        "ref", "ref_src", "spm", "_hsenc", "_hsmi", "yclid", "msclkid",
    }
)


def _strip_tracking(query: str) -> str:
    if not query:
        return ""
    kept = [(k, v) for k, v in parse_qsl(query) if k.lower() not in _TRACKING_PARAMS]
    return urlencode(kept)


# Line/block boilerplate that is NOT useful result content — page chrome the
# raw-scraping providers (notably jina) surface from rendered pages: cookie /
# consent walls, sign-in + blocked notices, site navigation, ad/tracker wires.
# Applied to the agent-facing `content` field only (never `raw_content`).
_BOILERPLATE_PATTERNS: tuple[str, ...] = (
    "cookie consent", "cookie preferences", "essential cookies",
    "accept all", "decline all", "manage consent", "customize cookie",
    "we use cookies", "this site uses cookies",
    "sign in", "sign in to", "log in", "log in to", "login to",
    "you've been blocked", "blocked by network security",
    "skip to main", "skip navigation", "skip to content",
    "navigation menu", "left sidebar", "appearance settings",
    "press ←", "press esc",
    "tap to unmute", "playback doesn't begin", "keyboard shortcuts",
    "sign up with google", "already have an account",
)

_BOILERPLATE_RE = re.compile("|".join(map(re.escape, _BOILERPLATE_PATTERNS)), re.IGNORECASE)


def _strip_boilerplate(text: str) -> str:
    """Remove obvious page-chrome / wall lines from a raw content string.

    Filters line-by-line so genuine prose around the junk survives. Returns the
    cleaned text; if BOILERPLATE_RE matches nothing, the input is returned
    unchanged (a no-op for already-clean providers).
    """
    if not text or not _BOILERPLATE_RE.search(text):
        return text
    out: list[str] = []
    for line in text.splitlines():
        if _BOILERPLATE_RE.search(line):
            continue
        out.append(line)
    cleaned = "\n".join(out).strip()
    return cleaned


def normalize_result(
    r: SearchResult,
    max_content_chars: int = CONTENT_CAP_CHARS,
    max_raw_chars: int = RAW_CAP_CHARS,
) -> SearchResult:
    """Return a copy of `r` with URL canonicalized, chrome stripped, and lengths capped.

    Single-sentence `content` (provider snippet vs full page) is preserved as-is
    when it already fits the cap — truncation only trims bloat, never expands.
    `raw_content` (the provider's full page body) is bounded to `max_raw_chars`
    so responses stay token-efficient; content and raw_content are kept distinct.
    """
    content = r.content or ""
    content = _strip_boilerplate(content)
    if len(content) > max_content_chars:
        content = _truncate(content, max_content_chars)
    raw = r.raw_content or ""
    if raw and len(raw) > max_raw_chars:
        raw = _truncate(raw, max_raw_chars)
    return SearchResult(
        title=(r.title or "").strip(),
        url=canonicalize_url(r.url),
        content=content,
        score=r.score,
        raw_content=raw,
    )


def _truncate(text: str, max_chars: int) -> str:
    """Hard-truncate at a word boundary, appending an ellipsis marker."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip(" .") + "…"


def dedup(results: list[SearchResult]) -> list[SearchResult]:
    """Exact-URL de-dup (post-canonicalization), keeping the most complete item.

    The first occurrence of a canonical URL wins; a later occurrence only
    replaces it if it carries more/better metadata (non-empty title + longer
    content). SOTA stage-1 dedup: exact match on canonicalized URL.
    """
    best: dict[str, SearchResult] = {}
    order: list[str] = []
    for r in results:
        norm = normalize_result(r)
        key = norm.url
        if not key:
            continue
        if key not in best:
            best[key] = norm
            order.append(key)
            continue
        cur = best[key]
        if _is_more_complete(norm, cur):
            best[key] = norm
    return [best[k] for k in order]


def _is_more_complete(candidate: SearchResult, current: SearchResult) -> bool:
    """True if `candidate` looks like a richer version of the same URL."""
    cand = (1 if candidate.title else 0) + min(1, len(candidate.content) // 20)
    curr = (1 if current.title else 0) + min(1, len(current.content) // 20)
    if cand != curr:
        return cand > curr
    return (candidate.score is not None) and (current.score is None or candidate.score > (current.score or 0))


def rrf_fuse(
    ranked_lists: list[list[SearchResult]],
    k: float = RRF_K,
    max_results: int = 5,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion of several ranked result lists into one ordering.

    Each result scores Σ 1/(k + rank) across the lists it appears in
    (URL-canonicalized), then all results are sorted descending by that score
    and truncated to `max_results`. Score-agnostic by design — per-provider
    `score` scales never enter the ranking. URLs present in only one list are
    not penalized (they just contribute a single term).
    """
    scores: dict[str, float] = {}
    best: dict[str, SearchResult] = {}
    for lst in ranked_lists:
        seen_in_list: set[str] = set()
        for rank, r in enumerate(lst, start=1):
            norm = normalize_result(r)
            key = norm.url
            if not key or key in seen_in_list:
                continue
            seen_in_list.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            cur = best.get(key)
            if cur is None or _is_more_complete(norm, cur):
                best[key] = norm
    ranked = sorted(best.values(), key=lambda r: (-scores[r.url], r.url))
    return ranked[: max(1, max_results)]


def tidiness_score(results: list[SearchResult], max_content_chars: int = CONTENT_CAP_CHARS) -> float:
    """0..1 compactness signal: 1.0 = every result fits the cap (no bloat).

    A provider that dumps full page bodies into `content` scores low, giving the
    bandit a token-efficiency signal without any LLM judge.
    """
    if not results:
        return 0.0
    total = 0.0
    for r in results:
        n = len(r.content or "")
        if n == 0:
            total += 0.75  # empty content is also low-quality, but minor bloat is worse
        else:
            total += min(1.0, max_content_chars / n)
    return total / len(results)
