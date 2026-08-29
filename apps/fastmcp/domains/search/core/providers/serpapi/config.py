"""SerpApi provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to SerpApi") and
would re-tune together. Module exports `SERPAPI = SerpApiConfig()` so call
sites read `SERPAPI.max_results` rather than scattered loose constants.

See https://serpapi.com (Google SERP via `/search.json` with API key in query
param; free tier = 250 searches/month, no card, recurring; supports
`organic_results[]`, optional `answer_box`, `ai_overview`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SerpApiConfig:
    """SerpApi search client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://serpapi.com"

    # Empty string → keyless (unavailable) mode. Set SERPAPI_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. SerpApi allows `num` up to 100 on paid plans;
    # free tier is rate-limited (1/sec), so keep the cap low to bound latency.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/search.json"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("SERPAPI_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


SERPAPI = SerpApiConfig()
