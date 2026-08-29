"""Tavily provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Tavily") and
would re-tune together. Module exports `TAVILY = TavilyConfig()` so call
sites read `TAVILY.max_results` (grouped, immutable) rather than scattered
loose constants.

See https://docs.tavily.com/documentation/api-credits (free tier = 1,000
credits/month; basic=1 credit, advanced=2 credits) and
https://docs.tavily.com/sdk/python/quick-start.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TavilyConfig:
    """Tavily Search API client knobs."""

    # API host. All endpoints below are relative to this.
    base_url: str = "https://api.tavily.com"

    # Empty string → keyless (rate-limited) mode. Set TAVILY_API_KEY to enable
    # the full free tier (1,000 credits/mo) and endpoints beyond /search.
    api_key: str = ""

    # Default search depth. `basic` = 1 credit, `advanced` = 2 credits.
    default_search_depth: str = "basic"
    # Cap on results returned. SDK upper bound is 20.
    max_results: int = 5
    # Hard cap so a runaway agent can't ask for more than the API allows.
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST paths (relative to base_url). Kept here so the service uses one
    # auth + client pattern for both search and usage.
    search_path: str = "/search"
    usage_path: str = "/usage"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        object.__setattr__(self, "api_key", os.getenv("TAVILY_API_KEY", ""))


TAVILY = TavilyConfig()
