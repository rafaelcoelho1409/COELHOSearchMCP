"""Priority router — failover across provider adapters.

Implements the SOTA multi-provider routing pattern (c.f. OmniRoute discussion
#139): a priority-ordered provider list; on a provider's quota/network error,
fail FAIL-FAST to the next (don't wait out long timeouts); mark the failing
provider on cooldown so subsequent calls skip it and let its health recover.

Phase 3 adds Exa/Jina/Linkup by appending to `PROVIDERS`; each must implement
`BaseSearchProvider` and raise `ProviderQuotaExceeded` on quota exhaustion.
"""
from __future__ import annotations

import logging
import time

from .providers.base import BaseSearchProvider
from .providers.exa import exa
from .providers.exceptions import ProviderQuotaExceeded
from .providers.firecrawl import firecrawl
from .providers.jina import jina
from .providers.linkup import linkup
from .providers.serper import serper
from .providers.tavily import tavily
from .providers.you import you
from .schemas import SearchInput, SearchResponse


logger = logging.getLogger(__name__)


class SearchRouter:
    """Tries providers in priority order until one serves the request.

    Cooldown map: provider name → unix time when its cooldown expires. A
    provider on cooldown is skipped. On `ProviderQuotaExceeded`, the provider
    is put on cooldown (honoring `retry_after_s` when available).
    """

    def __init__(self, providers: list[BaseSearchProvider]) -> None:
        self.providers: list[BaseSearchProvider] = providers
        self._cooldown_until: dict[str, float] = {}

    @property
    def provider_names(self) -> list[str]:
        """Names of all registered providers, in priority order."""
        return [p.name for p in self.providers]

    def available(self) -> list[BaseSearchProvider]:
        now = time.monotonic()
        return [p for p in self.providers if self._cooldown_until.get(p.name, 0.0) <= now]

    def _mark_cooldown(self, name: str, retry_after_s: float | None) -> None:
        if retry_after_s is None:
            retry_after_s = 60.0  # default cooldown when server gave no hint
        self._cooldown_until[name] = time.monotonic() + retry_after_s
        logger.warning("[router] %s on cooldown for %.1fs", name, retry_after_s)

    def status(self) -> list[dict]:
        """Current per-provider routing state (for the `search://providers` resource).

        Returns one dict per provider with `name`, `available` (not on
        cooldown), and `cooldown_remaining_s` (0 when available). Pure/sync —
        safe for a resource read.
        """
        now = time.monotonic()
        out = []
        for p in self.providers:
            until = self._cooldown_until.get(p.name, 0.0)
            remaining = max(0.0, until - now)
            out.append(
                {
                    "name": p.name,
                    "available": remaining <= 0.0,
                    "cooldown_remaining_s": round(remaining, 1),
                }
            )
        return out

    async def search(self, req: SearchInput, ctx=None) -> SearchResponse:
        """Dispatch per `req.provider`: a pinned name or `auto` (priority+failover).

        - `auto` (default): try providers in priority order, fail over on quota.
        - `tavily` / `exa` (pinned): route to exactly that provider. If the name
          is unknown or the provider is on cooldown / hit quota, fall back to
          `auto` so the agent still gets results rather than a hard error.

        Raises the last `ProviderQuotaExceeded` (or a network error) if every
        provider is exhausted or unavailable.
        """
        if req.provider and req.provider != "auto":
            pinned = self._by_name(req.provider)
            if pinned is not None:
                try:
                    return await pinned.search(req, ctx)
                except ProviderQuotaExceeded as e:
                    logger.warning(
                        "[router] pinned %s quota exceeded -> fallback auto",
                        pinned.name,
                    )
                    self._mark_cooldown(pinned.name, e.retry_after_s)
        return await self._search_auto(req, ctx)

    async def _search_auto(self, req: SearchInput, ctx=None) -> SearchResponse:
        last_error: Exception | None = None
        for provider in self.available():
            try:
                return await provider.search(req, ctx)
            except ProviderQuotaExceeded as e:
                logger.warning(
                    "[router] %s quota exceeded -> failover", provider.name
                )
                self._mark_cooldown(provider.name, e.retry_after_s)
                last_error = e
            except Exception as e:  # noqa: BLE001 — network/parse errors, not quota
                logger.error("[router] %s error: %s", provider.name, e)
                last_error = e
        if last_error is not None:
            raise last_error
        raise RuntimeError("search: no providers available")

    def _by_name(self, name: str) -> BaseSearchProvider | None:
        """Look up a provider by name, or None if not registered."""
        for p in self.providers:
            if p.name == name:
                return p
        return None


# Default router: Tavily, Exa, Jina, Linkup, You, Serper, Firecrawl.
router = SearchRouter([tavily, exa, jina, linkup, you, serper, firecrawl])
