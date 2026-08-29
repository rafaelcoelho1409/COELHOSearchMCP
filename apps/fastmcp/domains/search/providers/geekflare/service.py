"""Geekflare I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The `/search` endpoint is a POST with `x-api-key` header. We request JSON. When
`include_answer` is requested we pass `groundedAnswer: true` (costs 5 credits
vs 2 for a plain search) so the response carries an LLM-synthesized answer we
surface via `SearchResponse.answer`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ...schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import GEEKTFLARE
from .domain import normalize_answer, normalize_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class GeekflareClient:
    """Stateful Geekflare client owning config + a reused httpx session."""

    def __init__(self, config=GEEKTFLARE) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        want_answer = bool(req.include_answer)
        await _ctx_info(
            ctx,
            f"geekflare: searching '{req.query}' (max_results={max_results}, "
            f"groundedAnswer={want_answer})",
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("geekflare", retry_after_s=60.0)

        payload = {
            "query": req.query,
            "limit": max_results,
            "source": self.config.source,
            "format": "json",
        }
        if want_answer:
            payload["groundedAnswer"] = True

        headers = {
            "x-api-key": self.config.api_key,
            "Content-Type": "application/json",
        }

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    headers=headers,
                    json=payload,
                )
            except httpx.RequestError as e:
                logger.error("geekflare network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402, 403):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("geekflare", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        if str(data.get("apiStatus")).lower() != "success":
            # Non-2xx-ish API-level failure; treat 4xx-style as quota if present.
            code = data.get("apiCode")
            if code in (429, 402, 403, 401) or str(code).startswith("4"):
                raise ProviderQuotaExceeded("geekflare", retry_after_s=60.0)

        body = data.get("data")
        answer = normalize_answer(body)
        results = normalize_results(body, max_results=max_results)

        await _ctx_info(ctx, f"geekflare: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="geekflare",
            results=results,
            answer=answer,
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
    """Best-effort parse of Geekflare's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class GeekflareAdapter:
    """Protocol-conformant provider adapter for the router (BaseSearchProvider)."""

    name = "geekflare"

    def __init__(self, client: GeekflareClient | None = None) -> None:
        self._client = client or GeekflareClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining Geekflare credits, or None.

        Geekflare has no public live credit-balance endpoint (the 500 free
        credits/mo are dashboard-visible). Return None to signal "unknown".
        """
        return None
