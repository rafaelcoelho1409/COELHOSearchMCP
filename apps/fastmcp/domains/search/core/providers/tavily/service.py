"""Tavily I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain.normalize_results` (pure). Uses the official
`AsyncTavilyClient` which handles auth, retries, and typed exceptions.

The typed exception hierarchy (esp. `TavilyKeylessLimitError` carrying
`retry_after_seconds`) is the aggregator's failover signal: it's exactly what
the router (Phase 2) consumes to switch to Exa/Jina when Tavily's free tier
hits its rate limit.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from tavily import AsyncTavilyClient
from tavily import errors as tavily_errors

from ....schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import TAVILY
from .domain import normalize_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class TavilyAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `search_tavily`: exposes the uniform
    `search(req, ctx)` surface the `BaseSearchProvider` protocol and router
    expect, plus `name` and `search_credits_remaining()`.
    """

    name = "tavily"

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await search_tavily(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining plan credits from Tavily /usage (None if unknown)."""
        return await tavily_credits_remaining()


async def _ctx_info(ctx: Context | None, msg: str) -> None:
    """Log a progress/info message on ctx only if an MCP session is live.

    In direct/programmatic calls (and during tests) no session exists yet and
    `ctx.info` raises RuntimeError. Guard so the tool works both over the
    wire and when exercised directly.
    """
    if ctx is None:
        logger.info(msg)
        return
    rc = getattr(ctx, "request_context", None)
    if rc is None:
        logger.info(msg)
        return
    try:
        await ctx.info(msg)
    except RuntimeError:
        logger.info(msg)


async def search_tavily(req: SearchInput, ctx: Context | None = None) -> SearchResponse:
    """Run a search through the Tavily provider and return unified results.

    Raises:
        ProviderQuotaExceeded — when Tavily's keyless/credit limit is reached.
        httpx.RequestError / HTTPError — network-level failures (not quota).
    """
    await _ctx_info(ctx, f"tavily: searching '{req.query}' (max_results={req.max_results})")

    max_results = min(req.max_results, TAVILY.max_results_cap)

    # Reuse our own shared httpx.AsyncClient so connection pooling + our
    # per-tool rate-limit middleware govern the request.
    async with httpx.AsyncClient(timeout=TAVILY.timeout_s) as client:
        tavily = AsyncTavilyClient(api_key=TAVILY.api_key or None, client=client)
        try:
            raw = await tavily.search(
                query=req.query,
                search_depth=req.search_depth or TAVILY.default_search_depth,
                max_results=max_results,
                include_answer=req.include_answer,
                include_usage=True,
            )
        except tavily_errors.TavilyKeylessLimitError as e:
            raise ProviderQuotaExceeded(
                "tavily", retry_after_s=e.retry_after_seconds
            ) from e
        except tavily_errors.UsageLimitExceededError as e:
            raise ProviderQuotaExceeded("tavily") from e

    results = normalize_results(raw.get("results", []))
    answer = (raw.get("answer") or None) if req.include_answer else None

    await _ctx_info(ctx, f"tavily: {len(results)} results")

    return SearchResponse(
        query=req.query,
        provider="tavily",
        results=results,
        answer=answer,
    )


async def tavily_credits_remaining() -> int | None:
    """Query Tavily /usage for remaining plan credits.

    Returns the account's plan remaining credits, or None if the key is
    unset / the endpoint is unavailable. The /usage endpoint is itself
    rate-limited (10 requests / 10 min), so callers should cache.
    """
    if not TAVILY.api_key:
        return None

    async with httpx.AsyncClient(timeout=TAVILY.timeout_s) as client:
        resp = await client.get(
            f"{TAVILY.base_url}{TAVILY.usage_path}",
            headers={"Authorization": f"Bearer {TAVILY.api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    account = data.get("account", {})
    limit = account.get("plan_limit")
    used = account.get("plan_usage", 0)
    if limit is None:
        return None
    return max(0, int(limit) - int(used))
