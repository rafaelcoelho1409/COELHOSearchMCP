"""Jina provider package.

Exposes `jina` — a singleton `JinaAdapter` conforming to the
`BaseSearchProvider` protocol, ready to hand to the router.
"""
from .service import JinaAdapter

jina: JinaAdapter = JinaAdapter()

__all__ = ["jina"]
