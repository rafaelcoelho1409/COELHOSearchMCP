"""Resource: `search://providers`

Returns the router's current per-provider state (available vs on cooldown)
as JSON. Lets an MCP client load routing health as CONTEXT — e.g. an agent
deciding between a cheap/fast search vs waiting can first read this resource
instead of making a tool call.

Implementation: reads `router.status()` — pure/sync, no I/O.
"""
from __future__ import annotations

import json

from fastmcp import FastMCP

from ..router import router


def register(mcp: FastMCP) -> None:
    """Register `search://providers` on the root server."""

    @mcp.resource("search://providers")
    async def providers_status() -> str:
        """Return each search provider's current availability as JSON.

        Payload: `providers` (per-provider availability) plus `names` (the
        `provider` values `web_search` accepts). Use this to understand which
        provider will serve a `web_search` call, or to pick a specific one —
        a provider on cooldown is skipped until its cooldown expires.
        """
        return json.dumps(
            {
                "providers": router.status(),
                "names": router.provider_names,
            },
            default=str,
        )
