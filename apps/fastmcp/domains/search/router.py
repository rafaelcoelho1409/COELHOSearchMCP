"""FGTS-VA bandit router — SOTA provider selection for Search MCP.

Implements the full algorithm from `docs/ROUTING.md`:
- **FGTS-VA scoring** (NeurIPS 2025 arxiv:2511.02123) ranks providers per
  request by a learned contextual posterior, warm-started from researched
  quality priors (quality-first, recurring-before-one-time).
- **Circuit breaker** (CLOSED/OPEN/HALF-OPEN) fails fast on a dead provider —
  one fast rejection, not a cascade, not a long timeout.
- **BwK budget pre-filter** excludes providers whose free-tier budget is spent,
  so real requests never hit an exhausted arm (`bandit.is_available`).
- **Fail-fast failover**: on any failure, dispatch to the next-best scored arm.

State (posterior + breaker + budget) lives in the process-wide
`bandit.BanditService` singleton, persisted to an optional JSON file.
"""
from __future__ import annotations

import logging
import time

from .bandit import BanditService, get_or_create
from .bandit.domain import compose_reward, make_context_vector
from .bandit.params import EXPECTED_LATENCY_S
from .providers.base import BaseSearchProvider
from .providers.exa import exa
from .providers.exceptions import ProviderQuotaExceeded
from .providers.firecrawl import firecrawl
from .providers.geekflare import geekflare
from .providers.jina import jina
from .providers.linkup import linkup
from .providers.serpapi import serpapi
from .providers.serper import serper
from .providers.tavily import tavily
from .providers.tinyfish import tinyfish
from .providers.you import you
from .schemas import SearchInput, SearchResponse


logger = logging.getLogger(__name__)

# How many attempts before we give up and raise (prevents unbounded cascades).
MAX_ATTEMPTS = 6


class SearchRouter:
    """Tries providers in bandit-scored order until one serves the request.

    Ranking is decided by the FGTS-VA posterior (warm-started from researched
    quality priors); `available()` additionally hard-filters by circuit breaker
    state and remaining BwK budget. Every outcome updates the bandit so the
    router gets smarter with each request.
    """

    def __init__(
        self,
        providers: list[BaseSearchProvider],
        bandit: BanditService | None = None,
    ) -> None:
        self.providers: list[BaseSearchProvider] = providers
        self._by_name_cache = {p.name: p for p in providers}
        # Bind the process-wide bandit if not injected (tests may inject a stub).
        self.bandit = bandit or get_or_create([p.name for p in providers])

    @property
    def provider_names(self) -> list[str]:
        """Names of all registered providers, in priority order."""
        return [p.name for p in self.providers]

    def available(self) -> list[BaseSearchProvider]:
        """Arms the bandit considers dispatchable right now (breaker + BwK + cooldown)."""
        return [
            p
            for p in self.providers
            if self.bandit.is_available(p.name)
        ]

    def status(self) -> list[dict]:
        """Current per-provider routing state (for the `search://providers` resource)."""
        return self.bandit.status(self.provider_names)

    def _record_error(self, name: str, e: Exception) -> None:
        """Reward + breaker on a failed attempt."""
        retry = e.retry_after_s if isinstance(e, ProviderQuotaExceeded) else None
        error_class = "rate_limit" if isinstance(e, ProviderQuotaExceeded) else "unknown"
        if isinstance(e, ProviderQuotaExceeded):
            # Quota is a hard resource signal → cooldown immediately (BwK).
            self.bandit.record_failure(name, retry_after_s=retry)
            self.bandit.consume_budget(name, amount=1.0)
        else:
            self.bandit.record_failure(name)
        self.bandit.update_score(
            name,
            self._last_context,
            compose_reward(success=False, error_class=error_class),
        )

    async def search(self, req: SearchInput, ctx=None) -> SearchResponse:
        """Dispatch per `req.provider`: a pinned name or `auto` (scored + failover).

        - `auto` (default): rank available providers by FGTS-VA posterior, try
          them in that order, fail fast on any error.
        - `tavily` / `exa` (pinned): route to exactly that provider. If unknown /
          on cooldown / budget-exhausted / quota, fall back to `auto`.
        """
        self._last_context = make_context_vector(
            query=req.query,
            max_results=req.max_results,
            search_depth=req.search_depth,
            include_answer=req.include_answer,
        )
        if req.provider and req.provider != "auto":
            pinned = self._by_name(req.provider)
            if pinned is not None and self.bandit.is_available(pinned.name):
                try:
                    return await self._dispatch(pinned, req, ctx)
                except ProviderQuotaExceeded:
                    logger.warning(
                        "[router] pinned %s quota exceeded -> fallback auto",
                        pinned.name,
                    )
            else:
                logger.warning("[router] pinned %s unavailable -> fallback auto", req.provider)
        resp, last_error = await self._search_auto(req, ctx)
        if resp is not None:
            return resp
        if last_error is not None:
            raise last_error
        raise RuntimeError("search: no providers available (cooldown / budget exhausted)")

    async def _dispatch(self, provider: BaseSearchProvider, req: SearchInput, ctx=None) -> SearchResponse:
        """Call one provider, update the bandit (reward + breaker + budget), return or raise."""
        start = time.monotonic()
        try:
            resp: SearchResponse = await provider.search(req, ctx)
        except ProviderQuotaExceeded as e:
            self._record_error(provider.name, e)
            raise
        except Exception as e:  # noqa: BLE001 — network/parse errors
            self._record_error(provider.name, e)
            raise
        latency = time.monotonic() - start
        self.bandit.record_success(provider.name)
        self.bandit.consume_budget(provider.name, amount=1.0)
        self.bandit.update_score(
            provider.name,
            self._last_context,
            compose_reward(
                success=True,
                results_count=len(resp.results),
                latency_s=latency,
                expected_latency_s=EXPECTED_LATENCY_S,
                answer_present=bool(resp.answer),
            ),
        )
        logger.info(
            "[router] %s served in %.2fs (%d results, answer=%s)",
            provider.name, latency, len(resp.results), bool(resp.answer),
        )
        return resp

    async def _search_auto(self, req: SearchInput, ctx=None) -> tuple[SearchResponse | None, Exception | None]:
        """Fail-fast cascade: repeatedly pick the current best-scored available arm.

        After each failure the arm's score drops (and its breaker/cooldown may
        exclude it), so the next iteration picks a fresh best — a true cascade
        that only stops when every arm is exhausted/unavailable or a request
        succeeds. Bounded by MAX_ATTEMPTS as a safety valve.
        """
        last_error: Exception | None = None
        attempts = 0
        while attempts < MAX_ATTEMPTS:
            ranked = self._ranked(self.available())
            if not ranked:
                break
            provider = ranked[0]
            attempts += 1
            try:
                return await self._dispatch(provider, req, ctx), None
            except ProviderQuotaExceeded as e:
                logger.warning("[router] %s quota exceeded -> failover", provider.name)
                last_error = e
            except Exception as e:  # noqa: BLE001 — network/parse
                logger.error("[router] %s error: %s", provider.name, e)
                last_error = e
        return None, last_error

    def _ranked(self, healthy: list[BaseSearchProvider]) -> list[BaseSearchProvider]:
        """Order healthy arms by bandit score (best first), preserving stability."""
        names = [p.name for p in healthy]
        if not names:
            return []
        ranked = self.bandit.predict_top_k(self._last_context, names, k=len(names))
        order = {name: i for i, (name, *_rest) in enumerate(ranked)}
        return sorted(healthy, key=lambda p: order.get(p.name, len(healthy)))

    def _by_name(self, name: str) -> BaseSearchProvider | None:
        return self._by_name_cache.get(name)


# Default router — quality-first, recurring-quota providers ahead of one-time
# banks (recurring > pinned fallback rule). The BANDIT ultimately decides per-
# request order, warm-started from these researched priors (docs/QUOTA.md):
#   Linkup (92%) > You (91%) > Exa (85%) > Firecrawl (82%) > Geekflare (80%) >
#   Tavily (78%) > Serper (72%) > Jina (60%) > TinyFish (55%) > SerpApi (40%).
# Answer-capable recurring arms (Linkup/You/Geekflare/Tavily) lead the
# include_answer path.
router = SearchRouter([linkup, you, exa, geekflare, tavily, tinyfish, firecrawl, serper, jina, serpapi])
