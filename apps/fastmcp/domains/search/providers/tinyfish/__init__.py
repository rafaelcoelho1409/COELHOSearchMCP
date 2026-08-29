"""TinyFish provider package.

Exposes `tinyfish` — a singleton `TinyFishAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.

Free tier: search is free on every plan and does NOT draw from the wallet,
even at $0 balance (no card). ~30 req/min search rate limit.
"""
from .service import TinyFishAdapter

tinyfish: TinyFishAdapter = TinyFishAdapter()

__all__ = ["tinyfish"]
