"""SerpApi provider package.

Exposes `serpapi` — a singleton `SerpApiAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import SerpApiAdapter

serpapi: SerpApiAdapter = SerpApiAdapter()

__all__ = ["serpapi"]
