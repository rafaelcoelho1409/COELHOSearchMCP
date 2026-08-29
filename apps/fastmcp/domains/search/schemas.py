"""Shared, provider-agnostic schemas for the Search capability domain.

Per COELHO Nexus CODE-CONVENTIONS §4, `schemas.py` holds the Pydantic
validation boundary (what the LLM sees / what crosses the tool edge).

These types are intentionally provider-agnostic: every provider adapter
(Tavily, Exa, Jina, ...) normalizes into the same `SearchResult`, so the
router returns a unified response no matter which engine served the request.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    """Parameters accepted by the unified search tool (LLM-visible).

    This is the LEAST-COMMON-DENOMINATOR surface across providers. Providers
    that support more (e.g. Tavily's `topic=news`, `days`) expose those via
    their own adapter; only the fields here are guaranteed honored by every
    provider.
    """

    query: str = Field(description="Free-text search query.")
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of results to return (1-20).",
    )
    search_depth: str = Field(
        default="basic",
        description="'basic' (faster, cheaper) or 'advanced' (more thorough).",
    )
    include_answer: bool = Field(
        default=False,
        description="Include an LLM-generated answer summary when provider supports it.",
    )
    provider: str = Field(
        default="auto",
        description=(
            "Which search provider to use. 'auto' (default) lets the router pick "
            "by priority and fail over automatically. Or pin a specific provider: "
            "'tavily', 'exa', 'jina', 'linkup', 'you', 'serper', 'firecrawl', "
            "or 'serpapi'. Unrecognized/on-cooldown names fall back to 'auto'."
        ),
    )


class SearchResult(BaseModel):
    """A single normalized search result, agnostic of the backing provider.

    `score` is the provider's own relevance score (0-1 where available); it
    is NOT comparable across providers and is kept for reference only.
    """

    title: str = ""
    url: str = ""
    content: str = ""
    score: float | None = None
    raw_content: str | None = None


class SearchResponse(BaseModel):
    """Unified response from the search tool.

    The agent sees `results` plus an optional provider-generated `answer`
    and a `provider` tag so the router can report which engine served the
    request (useful for observability and quota attribution).
    """

    query: str
    provider: str
    results: list[SearchResult]
    answer: str | None = None
