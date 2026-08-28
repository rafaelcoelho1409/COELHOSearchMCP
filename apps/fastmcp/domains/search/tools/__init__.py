"""MCP Tools for the Search domain.

Tools are the ACTIONS an agent can take. Each module owns a `register(mcp)`;
the package `register(mcp)` aggregates them, exactly the Nexus convention.

    web_search  → the single unified search tool (router → providers)
    usage       → per-provider remaining free-tier credits
"""
from fastmcp import FastMCP

from . import usage, web_search


def register(mcp: FastMCP) -> None:
    """Register all Search MCP tools on the root server."""
    web_search.register(mcp)
    usage.register(mcp)
