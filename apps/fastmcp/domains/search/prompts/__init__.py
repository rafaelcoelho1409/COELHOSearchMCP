"""MCP Prompts for the Search domain.

Prompts are USER-INVOCABLE templated strings — different from internal agent
system_prompts. An external MCP-aware client (Claude Desktop, MCP Inspector)
can list + run them. Mirrors the Nexus `prompts/<name>.py` + composite
`register(mcp)` convention.

    /search_agent  → a parameterized search-and-synthesize workflow prompt.
"""
from fastmcp import FastMCP

from . import search_agent


def register(mcp: FastMCP) -> None:
    """Register all Search MCP prompts on the root server."""
    search_agent.register(mcp)
