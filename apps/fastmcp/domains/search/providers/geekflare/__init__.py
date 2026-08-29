"""Geekflare (Parallel AI) provider package.

Exposes `geekflare` — a singleton `GeekflareAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.

Free tier: 500 credits/month recurring, no card. Standard search = 2 credits,
grounded answer = 5 credits (≈250 plain searches/mo).
"""
from .service import GeekflareAdapter

geekflare: GeekflareAdapter = GeekflareAdapter()

__all__ = ["geekflare"]
