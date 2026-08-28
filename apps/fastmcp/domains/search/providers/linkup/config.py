"""Linkup provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Linkup") and
would re-tune together. Module exports `LINKUP = LinkupConfig()` so call
sites read `LINKUP.max_results` rather than scattered loose constants.

See https://docs.linkup.so (free tier; `/v1/search` with `depth` and
`outputType` in {searchResults, sourcedAnswer}).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LinkupConfig:
    """Linkup `/v1/search` client knobs."""

    # API host. The search endpoint is a POST to this host.
    base_url: str = "https://api.linkup.so"

    # Empty string → keyless (unavailable) mode. Set LINKUP_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. Linkup returns up to 20 by default; we slice
    # in the domain layer to this cap to bound token cost for the model.
    max_results: int = 5
    max_results_cap: int = 20

    # Search depth: `fast`, `standard`, or `deep` (higher = more thorough,
    # slower, costlier).
    default_depth: str = "standard"

    timeout_s: float = 60.0

    # REST path (relative to base_url).
    search_path: str = "/v1/search"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        object.__setattr__(self, "api_key", os.getenv("LINKUP_API_KEY", ""))


LINKUP = LinkupConfig()
