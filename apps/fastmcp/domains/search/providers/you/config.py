"""You.com provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to You.com") and
would re-tune together. Module exports `YOU = YouConfig()` so call sites read
`YOU.max_results` rather than scattered loose constants.

See https://you.com/docs/guides/search (Web Search API: `POST /v1/search` on
https://ydc-index.io; free tier = 100 queries/day WITHOUT an API key, or
`$100` signup credits with an API key; results are `results.web[]`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YouConfig:
    """You.com Web Search API client knobs."""

    # API host for the search endpoint. Note: the canonical host is the bare
    # `ydc-index.io` (no `api.` subdomain) per the official docs/examples.
    base_url: str = "https://ydc-index.io"

    # Empty string → keyless (free 100 queries/day) mode. Set YOUCOM_API_KEY
    # to unlock the full tool set / higher quota.
    api_key: str = ""

    # Cap on results returned. You.com allows 1-100 per call; keep our cap
    # lower to bound token cost for the consuming model.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/v1/search"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("YOUCOM_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


YOU = YouConfig()
