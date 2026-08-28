"""Shared provider-adapter exceptions.

`ProviderQuotaExceeded` is the single cross-provider signal the router
consumes for failover/cooldown. Every adapter (Tavily, Exa, Jina, Linkup)
raises this instead of leaking its vendor-specific error type, so the router
stays provider-agnostic.
"""
from __future__ import annotations


class ProviderQuotaExceeded(Exception):
    """Raised to signal the router that a provider's quota/rate-limit is spent.

    `retry_after_s` lets the router cooldown the provider accurately instead of
    hammering it while blocked.
    """

    def __init__(self, provider: str, retry_after_s: float | None = None) -> None:
        super().__init__(f"{provider} quota/rate-limit exceeded")
        self.provider = provider
        self.retry_after_s = retry_after_s
