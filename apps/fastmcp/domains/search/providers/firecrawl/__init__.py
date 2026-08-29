"""Firecrawl provider package.

Exposes `firecrawl` — a singleton `FirecrawlAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import FirecrawlAdapter

firecrawl: FirecrawlAdapter = FirecrawlAdapter()

__all__ = ["firecrawl"]
