"""Search capability domain — FastMCP registration.

Pattern: mirrors COELHO Nexus `domains/<capability>/server.py`. Each domain
owns a `register(mcp)` that composes the register functions of its three MCP
primitives (tools · resources · prompts) onto the root server. Providers and
the router are adapters/coordination, NOT MCP components — they live beside
these folders, not inside them (the Nexus infra-vs-feature split).

    domains/search/
    ├── server.py        ← register(mcp) composes everything below
    ├── tools/           ← web_search, usage (the agent's ACTIONS)
    ├── resources/       ← search://providers (agent's CONTEXT reads)
    ├── prompts/         ← /search_agent (agent's reusable templates)
    ├── router.py        ← coordination (priority + failover)
    ├── schemas.py       ← shared, provider-agnostic boundary types
    └── providers/       ← adapters (Tavily, then Exa/Jina/Linkup)

The agent sees ONE unified `web_search` tool; the router decides which backing
provider serves it. Providers are internal adapters, not separate domains.
"""
from __future__ import annotations

from fastmcp import FastMCP

from . import prompts, resources, tools


def register(mcp: FastMCP) -> None:
    """Register every Search MCP capability on the root server."""
    # Tools (2)
    tools.register(mcp)
    # Resources (1)
    resources.register(mcp)
    # Prompts (1)
    prompts.register(mcp)
