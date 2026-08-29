"""TinyFish I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The endpoint is a GET to the ROOT path (`GET {base}/?query=...`) with an
`X-API-Key` header and `query` param. When `include_answer` is requested there
is no answer payload to extract, but the docs recommend passing the intent via
the `purpose` param to improve ranking quality — so we forward
`req.query`+`req.include_answer` there for better result relevance.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ...schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import TINYFISH
from .domain import normalize_answer, normalize_results

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class TinyFishClient:
    """Stateful TinyFish client owning config + a reused httpx session."""

    def __init__(self, config=TINYFISH) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.config.api_key}

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        await _ctx_info(ctx, f"tinyfish: searching '{req.query}' (max_results={max_results})")

        if not self.config.api_key:
            raise ProviderQuotaExceeded("tinyfish", retry_after_s=60.0)

        params: dict[str, str | int] = {
            "query": req.query,
            "results": max_results,
        }
        if req.include_answer:
            # Forward intent to improve ranking; no answer payload comes back.
            params["purpose"] = req.query

        async with self.session() as client:
            try:
                resp = await client.get(
                    f"{self.config.base_url}{self.config.search_path}",
                    params=params,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("tinyfish network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402, 403):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("tinyfish", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        answer = normalize_answer(data)
        results = normalize_results(data, max_results=max_results)

        await _ctx_info(ctx, f"tinyfish: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="tinyfish",
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
    """Best-effort parse of TinyFish's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class TinyFishAdapter:
    """Protocol-conformant provider adapter for the router (BaseSearchProvider)."""

    name = "tinyfish"

    def __init__(self, client: TinyFishClient | None = None) -> None:
        self._client = client or TinyFishClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining TinyFish credits, or None.

        TinyFish search never draws from a quota balance (free at any wallet
        balance), so there is no queryable credit balance to report. Return
        None to signal "free/unmetered" rather than fabricate a number.
        """
        return None
