"""Exa provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Exa") and
would re-tune together. Module exports `EXA = ExaConfig()` so call sites read
`EXA.max_results` rather than scattered loose constants.

See https://exa.ai/docs/reference/search-api-guide (free tier = 1,000 requests/
month; first 10 results with full text included per request; search rate limit
10 QPS).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExaConfig:
    """Exa Search API client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://api.exa.ai"

    # Empty string → keyless (unavailable) mode. Set EXA_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. Exa allows 1-100; keep our cap lower to bound
    # token cost for the consuming model.
    max_results: int = 5
    max_results_cap: int = 20

    # Search type. `auto` is Exa's recency/semantic hybrid default.
    search_type: str = "auto"

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/search"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        object.__setattr__(self, "api_key", os.getenv("EXA_API_KEY", ""))


EXA = ExaConfig()
