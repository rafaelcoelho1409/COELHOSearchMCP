"""Firecrawl I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The `/v1/search` endpoint uses `Authorization: Bearer` auth and a JSON body of
`{"query", "limit"}`. The response is
`{"success": true, "data": [{"url", "title", "description"}, ...]}` where each
`description` is LLM-ready markdown. Firecrawl search exposes no native direct
answer, so `SearchResponse.answer` is always None.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ....schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import FIRECRAWL
from .domain import normalize_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class FirecrawlClient:
    """Stateful Firecrawl client owning config + a reused httpx session.

    Holds the connection pool and auth header so repeated searches don't
    re-handshake. Threads `api_key` from `FIRECRAWL` config.
    """

    def __init__(self, config=FIRECRAWL) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        await _ctx_info(
            ctx, f"firecrawl: searching '{req.query}' (max_results={max_results})"
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("firecrawl", retry_after_s=60.0)

        payload = {"query": req.query, "limit": max_results}

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    json=payload,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("firecrawl network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402, 403):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("firecrawl", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        # Firecrawl may wrap a non-2xx as {"success": false, "error": ...} even
        # with a 200 HTTP status — surface that as a non-web result.
        results = normalize_results(data.get("data", []), max_results=max_results)

        await _ctx_info(ctx, f"firecrawl: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="firecrawl",
            results=results,
            answer=None,  # Firecrawl search exposes no native answer
        )

    def session(self) -> httpx.AsyncClient:
        """Return a (lazily created, reused) httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def _ctx_info(ctx: Context | None, msg: str) -> None:
    """Log a progress/info message on ctx only if an MCP session is live."""
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


def _retry_after_s(resp: httpx.Response) -> float:
    """Best-effort parse of Firecrawl's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class FirecrawlAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `FirecrawlClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "firecrawl"

    def __init__(self, client: FirecrawlClient | None = None) -> None:
        self._client = client or FirecrawlClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining Firecrawl credits, or None.

        Firecrawl's 1,000-credit free allowance has no public balance endpoint —
        usage is only visible in the dashboard. Return None to signal "unknown"
        rather than fabricate a number (see BaseSearchProvider).
        """
        return None
