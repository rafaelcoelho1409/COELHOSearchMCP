"""TinyFish provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to TinyFish") and
would re-tune together. Module exports `TINYFISH = TinyFishConfig()` so call
sites read `TINYFISH.max_results` rather than scattered loose constants.

See https://docs.tinyfish.ai (Search API at `GET {base}/` with `?query=`; free
on every plan, does NOT draw from wallet even at $0 balance; no card; 30 req/min.
Returns `results[]` of `title`, `url`, `snippet`, `position`, `site_name`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TinyFishConfig:
    """TinyFish search client knobs."""

    # API host for the search endpoint.
    base_url: str = "https://api.search.tinyfish.ai"

    # Empty string → keyless (unavailable) mode. Set TINYFISH_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. TinyFish returns up to `results`; we slice in
    # the domain layer to this cap to bound token cost for the model.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url). The TinyFish Search API serves on the
    # ROOT path (e.g. `GET {base}/?query=...`); `/search` returns the web app
    # HTML instead, so keep this as "/".
    search_path: str = "/"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        # Strip surrounding quotes in case the .env was saved as `"..."`.
        raw = os.getenv("TINYFISH_API_KEY", "")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        object.__setattr__(self, "api_key", raw)


TINYFISH = TinyFishConfig()
