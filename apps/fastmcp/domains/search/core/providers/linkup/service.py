"""Linkup I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The `/v1/search` endpoint uses `Authorization: Bearer` auth and a JSON body
with `q`, `depth`, and `outputType`. We honor the unified `include_answer`
switch: `sourcedAnswer` when requested (yields an `answer` + `sources`),
else `searchResults` (clean result objects).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ....schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import LINKUP
from .domain import normalize_search_results, normalize_sources

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class LinkupClient:
    """Stateful Linkup client owning config + a reused httpx session.

    Holds the connection pool and auth header so repeated searches don't
    re-handshake. Threads `api_key` from `LINKUP` config.
    """

    def __init__(self, config=LINKUP) -> None:
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
            ctx, f"linkup: searching '{req.query}' (max_results={max_results})"
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("linkup", retry_after_s=60.0)

        # `sourcedAnswer` yields an answer + sources; `searchResults` yields
        # clean result objects. Honor the unified include_answer switch.
        output_type = "sourcedAnswer" if req.include_answer else "searchResults"
        payload = {
            "q": req.query,
            "depth": self.config.default_depth,
            "outputType": output_type,
        }

        async with self.session() as client:
            try:
                resp = await client.post(
                    f"{self.config.base_url}{self.config.search_path}",
                    json=payload,
                    headers=self._headers,
                )
            except httpx.RequestError as e:
                logger.error("linkup network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("linkup", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()

        if output_type == "sourcedAnswer":
            answer = (data.get("answer") or None)
            results = normalize_sources(data.get("sources", []), max_results=max_results)
        else:
            answer = None
            results = normalize_search_results(data.get("results", []), max_results=max_results)

        await _ctx_info(ctx, f"linkup: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="linkup",
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
    """Best-effort parse of Linkup's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class LinkupAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `LinkupClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "linkup"

    def __init__(self, client: LinkupClient | None = None) -> None:
        self._client = client or LinkupClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining Linkup credits, or None.

        Linkup has no public per-request credits-balance endpoint; credit
        balance is only visible in the dashboard. Return None to signal
        "unknown" rather than fabricate a number (see BaseSearchProvider).
        """
        return None
