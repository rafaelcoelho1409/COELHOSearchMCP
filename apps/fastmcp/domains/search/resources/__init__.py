"""MCP Resources for the Search domain.

Resources are the READ side of MCP — idempotent named entities an agent (or
an external MCP-aware client, or the MCP Inspector) can load as context
without paying a tool-call's cost. Mirrors the Nexus `resources/<name>.py` +
composite `register(mcp)` convention.

    search://providers  → current router state: which provider is serving,
                          which are on cooldown and for how long.
"""
from fastmcp import FastMCP

from . import providers_status


def register(mcp: FastMCP) -> None:
    """Register all Search MCP resources on the root server."""
    providers_status.register(mcp)
