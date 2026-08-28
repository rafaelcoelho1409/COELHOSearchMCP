"""Exa I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain.normalize_results` (pure).

The Exa `/search` endpoint uses `Authorization: Bearer` auth and a JSON body.
We call it with a shared `httpx.AsyncClient` (connection pooling). A 429
(from Exa's 10 QPS search rate limit) is the failover signal the router
consumes, translated into the cross-provider `ProviderQuotaExceeded`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ...schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import EXA
from .domain import normalize_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class ExaClient:
    """Stateful Exa client owning config + a reused httpx session.

    Holds the connection pool and auth header so repeated searches don't
    re-handshake. Threads `api_key` from `EXA` config.
    """

    def __init__(self, config=EXA) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        await _ctx_info(
            ctx, f"exa: searching '{req.query}' (max_results={max_results})"
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("exa", retry_after_s=60.0)

        payload = {
            "query": req.query,
            "type": self.config.search_type,
            "numResults": max_results,
            "contents": {"text": {"max_characters": 3000}},
        }

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    json=payload,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("exa network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code == 429:
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("exa", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        results = normalize_results(data.get("results", []))

        await _ctx_info(ctx, f"exa: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="exa",
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
    """Best-effort parse of Exa's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class ExaAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `ExaClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "exa"

    def __init__(self, client: ExaClient | None = None) -> None:
        self._client = client or ExaClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining Exa credits, or None.

        Exa does NOT expose a public credits-balance endpoint — remaining
        balance is only visible on the dashboard Billing page. So we return
        None to signal "unknown" rather than fabricate a number (see
        BaseSearchProvider.search_credits_remaining).
        """
        return None
