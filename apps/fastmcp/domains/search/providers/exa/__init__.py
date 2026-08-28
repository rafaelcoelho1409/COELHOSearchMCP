"""Exa provider package.

Exposes `exa` — a singleton `ExaAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import ExaAdapter

exa: ExaAdapter = ExaAdapter()

__all__ = ["exa"]
