"""Jina provider configuration — frozen-dataclass GROUP per COELHO Nexus
CODE-CONVENTIONS §3.

Tunables that describe one concept ("how this server talks to Jina") and
would re-tune together. Module exports `JINA = JinaConfig()` so call sites
read `JINA.max_results` rather than scattered loose constants.

See https://jina.ai/reader (s.jina.ai = web search returning LLM-friendly
markdown; free key = 100 RPM, each search ~10,000 tokens).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JinaConfig:
    """Jina `s.jina.ai` search client knobs."""

    # Search host. The search endpoint is a POST to the root path.
    base_url: str = "https://s.jina.ai"

    # Empty string → keyless (blocked) mode. Set JINA_API_KEY to enable.
    api_key: str = ""

    # Cap on results returned. s.jina.ai returns ~10 by default; we slice in
    # the domain layer to this cap to bound token cost for the model.
    max_results: int = 5
    max_results_cap: int = 20

    timeout_s: float = 60.0

    # REST path (relative to base_url) — the search endpoint is the root.
    search_path: str = "/"

    def __post_init__(self) -> None:
        # Read from env at instantiation (matches Nexus inject_user_keys pattern).
        object.__setattr__(self, "api_key", os.getenv("JINA_API_KEY", ""))


JINA = JinaConfig()
