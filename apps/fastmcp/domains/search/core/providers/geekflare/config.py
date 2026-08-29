"""Geekflare (Parallel AI) provider configuration — frozen-dataclass GROUP per
COELHO Nexus CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Geekflare") and
would re-tune together. Module exports `GEEKTFLARE = GeekflareConfig()` so call
sites read `GEEKTFLARE.max_results` rather than scattered loose constants.

See https://docs.geekflare.com (Search API at `POST {base}/search`; free tier =
500 credits/mo, no card, recurring; standard search = 2 credits; grounded
answer = 5 credits; returns `data[]` of `title`, `url`, `snippet`, `position`,
and with `groundedAnswer: true` returns an LLM-synthesized `answer` + sources).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeekflareConfig:
    """Geekflare search client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://api.geekflare.com"

    # Empty string → keyless (unavailable) mode. Set GEEKTFLARE_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. Standard search costs 2 credits/call regardless
    # of limit, so the cap mostly bounds response size/latency, not cost.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/search"

    # Search source for the provider: "web" | "news" | "images".
    source: str = "web"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("GEEKTFLARE_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


GEEKTFLARE = GeekflareConfig()
