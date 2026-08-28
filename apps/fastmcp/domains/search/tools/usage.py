"""Tool: `usage` — per-provider remaining free-tier credits.

Lets an agent (or operator) check how much free quota each search provider
has left, so it can budget tool calls instead of hitting rate limits blind.

Uniform contract: `usage` iterates every registered provider and queries its
`search_credits_remaining()`. Providers with no live balance endpoint (Exa)
return None, which we surface honestly as "unknown" — no fabricated numbers.

The Tavily /usage endpoint is itself rate-limited (10 req / 10 min), so this
tool is a manual/situational check, not something to call in a hot loop.
"""
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from ..router import router


class UsageReport(BaseModel):
    """Free-tier quota for a single provider."""

    provider: str
    remaining_credits: int | None


def register(mcp: FastMCP) -> None:
    """Register the `usage` tool on the given FastMCP server."""

    @mcp.tool
    async def usage(provider: str = "all") -> list[UsageReport]:
        """Report remaining free-tier credits for search providers.

        Pass `provider='all'` (default) to report every registered provider,
        or a specific name (e.g. 'tavily') for just one. A provider reports
        `remaining_credits=None` when it has no queryable balance (Exa's
        balance is dashboard-only) or no API key configured.

        Args:
            provider: 'all' (default) or a specific provider name.

        Returns:
            A list of UsageReport, one per requested provider.
        """
        targets = router.providers
        if provider != "all":
            targets = [p for p in router.providers if p.name == provider]
            if not targets:
                known = ", ".join(router.provider_names)
                raise ToolError(
                    f"Unknown provider '{provider}'; known: {known or '(none)'}"
                )

        reports: list[UsageReport] = []
        for p in targets:
            remaining: int | None = None
            try:
                remaining = await p.search_credits_remaining()
            except Exception as e:  # noqa: BLE001 — surface per-provider, don't abort all
                remaining = None
            reports.append(
                UsageReport(provider=p.name, remaining_credits=remaining)
            )
        return reports
