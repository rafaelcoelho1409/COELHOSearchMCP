"""Tavily provider package.

Exposes `tavily` — a singleton `TavilyAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import TavilyAdapter

tavily: TavilyAdapter = TavilyAdapter()

__all__ = ["tavily"]
