"""Serper provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Serper") and
would re-tune together. Module exports `SERPER = SerperConfig()` so call
sites read `SERPER.max_results` rather than scattered loose constants.

See https://serper.dev (Google SERP: `POST google.serper.dev/search` with an
`X-API-KEY` header and a JSON body of `{"q", "num"}`; free tier = 2,500
searches/month, no card; results are `organic[]`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SerperConfig:
    """Serper Google SERP client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://google.serper.dev"

    # Empty string → keyless (unavailable) mode. Set SERPER_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. Serper allows a `num` 1-100; keep our cap lower
    # to bound token cost for the consuming model.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/search"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("SERPER_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


SERPER = SerperConfig()
