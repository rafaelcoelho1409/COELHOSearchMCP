"""Provider adapter protocol — the Ports & Adapters boundary.

Every search provider (Tavily, Exa, Jina, Linkup) implements this protocol.
The router depends only on this interface, so adding a provider is purely
additive: write a `providers/<name>/` package exposing `search()`, register it
in the router's priority list, done.

Naming note: this mirrors COELHO Nexus's `infra/` split — providers are
adapters (ports), not bounded contexts. They implement capabilities; the
`search` domain owns the unified tool surface.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import SearchInput, SearchResponse  # noqa: F401  (re-export)
from .exceptions import ProviderQuotaExceeded  # noqa: F401  (re-export)


@runtime_checkable
class BaseSearchProvider(Protocol):
    """Async search contract shared by all providers.

    Implementations MUST raise `ProviderQuotaExceeded` when their free-tier or
    rate limit is hit, so the router can fail over cleanly.
    """

    name: str  # e.g. "tavily", "exa", "jina"

    async def search(self, req: SearchInput, ctx=None) -> SearchResponse: ...

    async def search_credits_remaining(self) -> int | None:
        """Return remaining free-tier credits, or None if not queryable.

        Some providers (e.g. Tavily `/usage`) expose a live balance endpoint;
        others (e.g. Exa) do not — balance is dashboard-only — so adapters
        return None to signal "unknown" rather than fabricating a number.
        """
