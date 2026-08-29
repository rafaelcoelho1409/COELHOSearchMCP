"""SerpApi I/O orchestration — the Imperative Shell.

Per COELHO Nexus CODE-CONVENTIONS §4: async + httpx here; all normalization
delegated to `domain` (pure).

The `/search.json` endpoint uses API key in query param (`api_key`) and is a
GET request with `q`, `engine=google`, and `num` params. The response is a JSON
object carrying `organic_results[]` (organic results) and an optional
`answer_box` (Google's direct answer). We surface `answer_box` when present.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ....schemas import SearchInput, SearchResponse
from ..exceptions import ProviderQuotaExceeded
from .config import SERPAPI
from .domain import normalize_answer, normalize_organic

if TYPE_CHECKING:
    from fastmcp import Context


logger = logging.getLogger(__name__)


class SerpApiClient:
    """Stateful SerpApi client owning config + a reused httpx session.

    Holds the connection pool and auth so repeated searches don't
    re-handshake. Threads `api_key` from `SERPAPI` config.
    """

    def __init__(self, config=SERPAPI) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        max_results = min(req.max_results, self.config.max_results_cap)
        await _ctx_info(
            ctx, f"serpapi: searching '{req.query}' (max_results={max_results})"
        )

        if not self.config.api_key:
            raise ProviderQuotaExceeded("serpapi", retry_after_s=60.0)

        params = {
            "q": req.query,
            "engine": "google",
            "api_key": self.config.api_key,
            "num": max_results,
        }

        async with self.session() as client:
            try:
                resp = await client.get(
                    f"{self.config.base_url}{self.config.search_path}",
                    params=params,
                )
            except httpx.RequestError as e:
                logger.error("serpapi network error: %s", e)
                raise  # network — not quota; surfaced to router

        if resp.status_code in (429, 402, 403):
            retry = _retry_after_s(resp)
            raise ProviderQuotaExceeded("serpapi", retry_after_s=retry)
        resp.raise_for_status()

        data = resp.json()
        answer = normalize_answer(data.get("answer_box"))
        results = normalize_organic(data.get("organic_results", []), max_results=max_results)

        await _ctx_info(ctx, f"serpapi: {len(results)} results")
        return SearchResponse(
            query=req.query,
            provider="serpapi",
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
    """Best-effort parse of SerpApi's Retry-After header (seconds or HTTP date)."""
    if resp is None:
        return 60.0
    value = resp.headers.get("Retry-After")
    if not value:
        return 60.0
    try:
        return float(value)
    except ValueError:
        return 60.0


class SerpApiAdapter:
    """Protocol-conformant provider adapter for the router.

    Thin wrapper around `SerpApiClient`: exposes the uniform `search(req, ctx)`
    surface the `BaseSearchProvider` protocol and router expect, plus `name`.
    """

    name = "serpapi"

    def __init__(self, client: SerpApiClient | None = None) -> None:
        self._client = client or SerpApiClient()

    async def search(self, req: SearchInput, ctx: Context | None = None) -> SearchResponse:
        return await self._client.search(req, ctx)

    async def search_credits_remaining(self) -> int | None:
        """Return remaining SerpApi credits, or None.

        SerpApi has an Account API (`/account.json`) that returns
        `plan_searches_left`, but it's rate-limited and burns a search call.
        Return None to signal "unknown" rather than fabricate a number (see
        BaseSearchProvider). The account balance is visible in the dashboard.
        """
        return None
