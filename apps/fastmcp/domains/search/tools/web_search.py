"""Tool: `web_search` — the single unified search surface.

Boundary layer per Nexus CODE-CONVENTIONS §4: this file stays a THIN shell.
The `@mcp.tool` decorator binds the Pydantic schemas + async signature; the
body is one call into `router.search` with error→ToolError mapping at the
boundary.

The agent only ever sees THIS tool. The router decides which backing provider
(Tavily, then Exa/Jina/Linkup) serves the request — providers are internal
adapters, not exposed tools.
"""
from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from ..core.providers.exceptions import ProviderQuotaExceeded
from ..router import router
from ..schemas import SearchInput, SearchResponse


def register(mcp: FastMCP) -> None:
    """Register the `web_search` tool on the given FastMCP server."""

    @mcp.tool
    async def web_search(
        ctx: Context,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = False,
        provider: str = "auto",
    ) -> SearchResponse:
        """Search the web for current information.

        Returns normalized web results from a pool of free search providers,
        with automatic failover. Choose a specific provider with `provider`
        (default 'auto' picks by priority and fails over automatically).

        Args:
            query: Free-text search query.
            max_results: Number of results to return (1-20, default 5).
            search_depth: 'basic' (fast/cheap) or 'advanced' (thorough).
            include_answer: Include an LLM-generated answer summary.
            provider: 'auto' (default), 'tavily', or 'exa'.

        Returns:
            A SearchResponse with normalized `results`, the serving `provider`
            name, and an optional `answer`.
        """
        req = SearchInput(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=include_answer,
            provider=provider,
        )
        try:
            return await router.search(req, ctx)
        except ProviderQuotaExceeded as e:
            raise ToolError(
                f"All search providers are exhausted: {e}"
            ) from e
