"""Firecrawl provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Firecrawl") and
would re-tune together. Module exports `FIRECRAWL = FirecrawlConfig()` so call
sites read `FIRECRAWL.max_results` rather than scattered loose constants.

See https://firecrawl.dev (native `/v1/search`; free tier = 1,000 credits/mo,
no card; search = 2 credits per 10 results; returns `data[]` of `url`, `title`,
`description` — the description is LLM-ready markdown).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FirecrawlConfig:
    """Firecrawl search client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://api.firecrawl.dev"

    # Empty string → keyless (unavailable) mode. Set FIRECRAWL_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. Firecrawl search costs 2 credits per 10 results
    # (rounded up), so a smaller cap keeps the free tier alive longer.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/v1/search"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("FIRECRAWL_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


FIRECRAWL = FirecrawlConfig()
