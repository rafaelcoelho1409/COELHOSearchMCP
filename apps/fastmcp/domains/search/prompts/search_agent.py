"""Prompt: `/search_agent`

A USER-invokable templated prompt that returns a reusable search-and-
synthesize workflow the operator can paste into another agent or run
directly. Mirrors the Nexus `rr/prompts/digest_today.py` pattern.
"""
from __future__ import annotations

from fastmcp import FastMCP


_TEMPLATE = """\
Search the web and synthesize an answer to the following topic:

Topic: {topic}
Search depth: {depth}
Max results per query: {max_results}
Include an LLM-generated answer summary: {include_answer}

Workflow:
1. Issue a `web_search` call for the topic. If the query is broad, run
   2-3 variations to cover different angles.
2. Optionally read `search://providers` first to confirm a provider is
   available (a provider on cooldown is skipped by the router anyway).
3. Condense the top results into a succinct, sourced summary. Cite the
   result URL for each key claim.

If the free-tier quota is exhausted (the search returns a quota error),
report that the request is rate-limited and suggest retrying later.
"""


def register(mcp: FastMCP) -> None:
    """Register `/search_agent` on the root server."""

    @mcp.prompt(name="search_agent")
    def search_agent(
        topic: str = "latest developments in search MCP servers",
        depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = False,
    ) -> str:
        """Generate a web-search-and-synthesize workflow for a topic.

        Args:
            topic: 2-6 word topical phrase (e.g. 'agentic web search 2026').
            depth: 'basic' (fast/cheap) or 'advanced' (thorough).
            max_results: Results per query (1-20).
            include_answer: Whether to request an LLM answer summary.
        """
        return _TEMPLATE.format(
            topic=topic.strip() or "latest developments in search MCP servers",
            depth="advanced" if depth == "advanced" else "basic",
            max_results=max(1, min(20, int(max_results))),
            include_answer="true" if include_answer else "false",
        )
