"""You.com I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The `/v1/search` endpoint uses `X-API-Key` auth (Optional — the free tier
works keyless at 100 queries/day) and a JSON body with `query`, `count`, and
optional domain/freshness filters. We prefer `results.web`; if it's empty we
fall back to `results.news` (same shape).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ....schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import YOU
from .domain import normalize_news, normalize_web

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class YouClient:
    """Stateful You.com client owning config + a reused httpx session.

    Holds the connection pool and auth header so repeated searches don't
    re-handshake. Threads `api_key` from `YOU` config.
    """

    def __init__(self, config=YOU) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        return headers

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        await _ctx_info(
            ctx, f"you: searching '{req.query}' (max_results={max_results})"
        )

        payload = {
            "query": req.query,
            "count": max_results,
        }

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    json=payload,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("you network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402, 403):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("you", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        results_container = data.get("results") or {}
        web = results_container.get("web") or []
        if web:
            results = normalize_web(web, max_results=max_results)
        else:
            results = normalize_news(results_container.get("news") or [], max_results=max_results)

        await _ctx_info(ctx, f"you: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="you",
            results=results,
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
    """Best-effort parse of You.com's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class YouAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `YouClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "you"

    def __init__(self, client: YouClient | None = None) -> None:
        self._client = client or YouClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining You.com credits, or None.

        You.com's free tier is a daily 100-query allowance (no live balance
        endpoint to query); paid usage is visible only in the platform
        dashboard. Return None to signal "unknown" rather than fabricate a
        number (see BaseSearchProvider).
        """
        return None
