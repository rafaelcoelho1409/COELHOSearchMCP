"""Jina I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all parsing
delegated to `domain.parse_results` (pure).

The `s.jina.ai` search endpoint is a POST to the root path with a JSON body
`{"q": query}` and `Authorization: Bearer` auth. It returns LLM-friendly
plain-text markdown, which the domain layer parses into unified results.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ...schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import JINA
from .domain import parse_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class JinaClient:
    """Stateful Jina client owning config + a reused httpx session.

    Holds the connection pool and auth header so repeated searches don't
    re-handshake. Threads `api_key` from `JINA` config.
    """

    def __init__(self, config=JINA) -> None:
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
            ctx, f"jina: searching '{req.query}' (max_results={max_results})"
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("jina", retry_after_s=60.0)

        payload = {"q": req.query}

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    json=payload,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("jina network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code == 429:
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("jina", retry_after_s=retry)
        # Jina raises 401/402 (unauthorized/quota) via status codes too.
        if resp.status_code in (401, 402, 403):
            raise ProviderQuotaExceeded("jina", retry_after_s=60.0)
        resp.raise_for_status()

        results = parse_results(resp.text, max_results=max_results)

        await _ctx_info(ctx, f"jina: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="jina",
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
    """Best-effort parse of Jina's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class JinaAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `JinaClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "jina"

    def __init__(self, client: JinaClient | None = None) -> None:
        self._client = client or JinaClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining Jina credits, or None.

        Jina has no public per-request credits-balance endpoint; the free tier
        is a fixed allowance (no queryable whitelist). Return None to signal
        "unknown" rather than fabricate a number (see BaseSearchProvider).
        """
        return None
