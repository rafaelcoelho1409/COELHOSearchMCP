"""Linkup provider package.

Exposes `linkup` — a singleton `LinkupAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import LinkupAdapter

linkup: LinkupAdapter = LinkupAdapter()

__all__ = ["linkup"]
