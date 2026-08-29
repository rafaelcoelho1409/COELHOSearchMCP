"""You.com provider package.

Exposes `you` — a singleton `YouAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import YouAdapter

you: YouAdapter = YouAdapter()

__all__ = ["you"]
