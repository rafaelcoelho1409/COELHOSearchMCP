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

from .core.bandit import BanditService, get_or_create
from .core.bandit.domain import compose_reward, make_context_vector
from .core.bandit.params import EXPECTED_LATENCY_S
from .fusion import dedup, normalize_result, rrf_fuse, tidiness_score
from .core.providers.base import BaseSearchProvider
from .core.providers.exa import exa
from .core.providers.exceptions import ProviderQuotaExceeded
from .core.providers.firecrawl import firecrawl
from .core.providers.geekflare import geekflare
from .core.providers.jina import jina
from .core.providers.linkup import linkup
from .core.providers.serpapi import serpapi
from .core.providers.serper import serper
from .core.providers.tavily import tavily
from .core.providers.tinyfish import tinyfish
from .core.providers.you import you
from .schemas import SearchInput, SearchResponse


logger = logging.getLogger(__name__)

# How many attempts before we give up and raise (prevents unbounded cascades).
MAX_ATTEMPTS = 6

# Providers fused on the quality ensemble path (see ROUTING.md §7). Higher =
# richer pool but more quota burn; 3 is the SOTA "retrieve wide, rerank narrow"
# balance. Set to 1 to preserve free-tier quota: exactly one provider per
# request, maximizing the number of searches you can serve.
ENSEMBLE_SIZE = 1


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
        self._last_max_results = req.max_results
        if req.provider and req.provider != "auto":
            pinned = self._by_name(req.provider)
            if pinned is not None and self.bandit.is_available(pinned.name):
                try:
                    resp = await self._dispatch(pinned, req, ctx)
                    return self._normalize_single(resp)
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

    async def _dispatch(
        self,
        provider: BaseSearchProvider,
        req: SearchInput,
        ctx=None,
        *,
        book_reward: bool = True,
    ) -> tuple[SearchResponse, float] | SearchResponse:
        """Call one provider, update the bandit (reward + breaker + budget), return or raise.

        By default books a reward and returns the bare response (single-provider
        path). When `book_reward=False` (ensemble path) the caller books the
        fused quality-loaded reward later, so this returns `(resp, latency_s)`.
        """
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
        if book_reward:
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
        return (resp, latency) if not book_reward else resp

    def _is_ensemble(self, req: SearchInput) -> bool:
        """Quality ensemble path: `include_answer` or `advanced` depth.

        These are the requests where fusion quality pays off most (an answer
        or a thorough pool deserves the extra quota). Plain basic/`include_answer=False`
        stays on the cheap single-provider path that never burns extra quota.
        """
        return bool(req.include_answer) or req.search_depth == "advanced"

    def _normalize_single(self, resp: SearchResponse) -> SearchResponse:
        """Cap bloated content + de-dup URLs for a single-provider response.

        Fixes the cross-provider consistency gap (e.g. Firecrawl raw-page bloat)
        even on the cheap path, deterministically, with zero extra latency.
        """
        seen_urls: set[str] = set()
        cleaned: list = []
        for r in dedup(resp.results):
            if not r.url or r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            cleaned.append(normalize_result(r))
        return SearchResponse(
            query=resp.query,
            provider=resp.provider,
            results=cleaned[: self._last_max_results],
            answer=resp.answer,
        )

    async def _search_auto(self, req: SearchInput, ctx=None) -> tuple[SearchResponse | None, Exception | None]:
        """Dispatch per path:
        - **basic** (default): fail-fast single-provider cascade (cheap, current
          behavior) + deterministic content/URL normalization of the winner.
        - **advanced / include_answer**: quality ensemble — try the top
          `ENSEMBLE_SIZE` available arms, fuse their results with RRF, de-dup,
          then book a fusion-survival + tidiness quality reward per contributor.

        Every failure records a penalty so the next iteration picks a fresh best;
        bounded by MAX_ATTEMPTS as a safety valve.
        """
        if not self._is_ensemble(req):
            last_error: Exception | None = None
            attempts = 0
            while attempts < MAX_ATTEMPTS:
                ranked = self._ranked(self.available())
                if not ranked:
                    break
                provider = ranked[0]
                attempts += 1
                try:
                    resp = await self._dispatch(provider, req, ctx)
                    return self._normalize_single(resp), None
                except ProviderQuotaExceeded as e:
                    logger.warning("[router] %s quota exceeded -> failover", provider.name)
                    last_error = e
                except Exception as e:  # noqa: BLE001 — network/parse
                    logger.error("[router] %s error: %s", provider.name, e)
                    last_error = e
            return None, last_error

        return await self._search_ensemble(req, ctx)

    async def _search_ensemble(self, req: SearchInput, ctx=None) -> tuple[SearchResponse | None, Exception | None]:
        """Fuse a small ensemble of the top-scored available arms (ROUTING.md §7)."""
        last_error: Exception | None = None
        attempts = 0
        used: set[str] = set()
        contributed: list[tuple[str, SearchResponse, float]] = []

        def _next_targets() -> list[BaseSearchProvider]:
            return [p for p in self._ranked(self.available()) if p.name not in used]

        while attempts < MAX_ATTEMPTS and len(contributed) < ENSEMBLE_SIZE:
            targets = _next_targets()
            if not targets:
                break
            provider = targets[0]
            used.add(provider.name)
            attempts += 1
            try:
                resp, latency = await self._dispatch(provider, req, ctx, book_reward=False)
                contributed.append((provider.name, resp, latency))
            except ProviderQuotaExceeded as e:
                logger.warning("[router] ensemble %s quota exceeded -> skip", provider.name)
                last_error = e
            except Exception as e:  # noqa: BLE001 — network/parse
                logger.error("[router] ensemble %s error: %s", provider.name, e)
                last_error = e

        if not contributed:
            return None, last_error

        # Each provider's (normalized, de-duped) contributed list.
        per_provider: dict[str, list] = {}
        for name, resp, _lat in contributed:
            per_provider[name] = dedup([normalize_result(r) for r in resp.results if r.url])

        fused = rrf_fuse([per_provider[n] for n in per_provider], max_results=self._last_max_results)

        answer = next((r.answer for (_n, r, _l) in contributed if r.answer), None)

        # Book quality-loaded rewards per contributor (fusion-survival + tidiness).
        fused_urls = {r.url for r in fused}
        for name, resp, latency in contributed:
            mine = per_provider[name]
            if not mine:
                continue
            survived = sum(1 for r in mine if r.url in fused_urls)
            survival = survived / len(mine) if mine else 0.0
            tidy = tidiness_score([normalize_result(r) for r in resp.results])
            self.bandit.update_score(
                name,
                self._last_context,
                compose_reward(
                    success=True,
                    results_count=len(fused),
                    latency_s=latency,
                    expected_latency_s=EXPECTED_LATENCY_S,
                    answer_present=bool(answer) and answer is resp.answer,
                    fusion_survival=survival,
                    tidiness=tidy,
                ),
            )

        resp = SearchResponse(
            query=req.query,
            provider=",".join(per_provider.keys()) or "auto",
            results=fused,
            answer=answer,
        )
        return resp, None

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
