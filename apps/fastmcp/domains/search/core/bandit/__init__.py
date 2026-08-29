"""FGTS-VA bandit router — SOTA provider selection for Search MCP.

Mirrors COELHO Nexus `domains/llm/rotator/bandit/` with the three SOTA
upgrades from `docs/ROUTING.md` §4:
  - circuit breaker (CLOSED/OPEN/HALF-OPEN)
  - discounted / sliding-window forgetting (non-stationarity)
  - BwK budget pre-filter (never route to an exhausted provider)

The router (`..router.SearchRouter`) owns coordination; this package provides
the scoring + health state that ranking consumes.
"""
from . import config, domain, entities, params, service  # noqa: F401
from .service import BanditService, get_or_create

__all__ = [
    "BanditService",
    "get_or_create",
    "config",
    "domain",
    "entities",
    "params",
    "service",
]
