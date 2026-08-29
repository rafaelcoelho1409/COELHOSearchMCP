"""Serper provider package.

Exposes `serper` — a singleton `SerperAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import SerperAdapter

serper: SerperAdapter = SerperAdapter()

__all__ = ["serper"]
