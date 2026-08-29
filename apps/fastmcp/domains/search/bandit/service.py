"""FGTS-VA bandit service — in-memory store + predict/update + persistence.

The **Imperative Shell** around the pure scoring core in `domain.py`. Holds
per-provider `CellState` (posterior) and `ProviderHealth` (breaker + budget),
warm-started from researched benchmark priors, and persists to an optional JSON
file (set `SEARCH_BANDIT_STATE_FILE`; empty = in-memory only). NO Redis is
required in this MCP.

Env:
  SEARCH_BANDIT_MODE={ucb,ts,fgts_va} > SEARCH_DISABLE_FGTS_VA=1 (→ts) > fgts_va
  SEARCH_BANDIT_STATE_FILE=/path/state.json  (option to survive restarts)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np

from .domain import Mode, score_cell
from .entities import BreakerState, CellState, ProviderHealth
from .params import (
    BREAKER_COOLDOWN_S,
    BREAKER_FAIL_THRESHOLD,
    BUDGET_EXHAUST_THRESHOLD,
    PROVIDER_BENCHMARK_PRIOR,
    UCB_ALPHA,
)


logger = logging.getLogger(__name__)


def _resolve_mode(override: Mode | None = None) -> Mode:
    if override is not None:
        return override
    explicit = os.environ.get("SEARCH_BANDIT_MODE", "").strip().lower()
    if explicit in ("ucb", "ts", "fgts_va"):
        return explicit  # type: ignore[return-value]
    if os.environ.get("SEARCH_DISABLE_FGTS_VA") == "1":
        return "ts"
    return "fgts_va"


# numpy.Generator draws are safe to call concurrently from asyncio coroutines.
_RNG = np.random.default_rng()


class BanditService:
    """Stateful FGTS-VA bandit over the registered search providers.

    One instance is a singleton (`BanditService.instance(default_providers)`).
    The router is the consumer: it calls `predict_top_k` to rank available arms,
    `update_score` after each outcome, `record_success/failure` on the breaker,
    and `consume_budget` for BwK bookkeeping.
    """

    def __init__(self, providers: list[str], mode: Mode | None = None) -> None:
        self.mode: Mode = _resolve_mode(mode)
        self.cells: dict[str, CellState] = {}
        self.health: dict[str, ProviderHealth] = {}
        self._state_file = os.environ.get("SEARCH_BANDIT_STATE_FILE", "")
        self._consecutive_global_failures: int = 0
        for name in providers:
            self.cells[name] = CellState.fresh(
                name, PROVIDER_BENCHMARK_PRIOR.get(name, 0.0)
            )
            self.health[name] = ProviderHealth(
                provider=name,
                fail_threshold=BREAKER_FAIL_THRESHOLD,
                cooldown_s=BREAKER_COOLDOWN_S,
            )
        self._load()
        logger.info(
            "[bandit] initialized %d provider arms, mode=%s", len(self.cells), self.mode
        )

    # --- Persistence (best-effort JSON) -------------------------------------
    def _load(self) -> None:
        if not self._state_file or not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file, encoding="utf-8") as fh:
                data = json.load(fh)
            for name, d in (data.get("cells") or {}).items():
                if name in self.cells:
                    self.cells[name] = CellState.from_dict(d)
            for name, d in (data.get("health") or {}).items():
                if name in self.health:
                    self.health[name] = ProviderHealth.from_dict(d)
            logger.info("[bandit] restored state from %s", self._state_file)
        except Exception as e:  # noqa: BLE001
            logger.warning("[bandit] state load failed from %s: %s", self._state_file, e)

    def _save(self) -> None:
        if not self._state_file:
            return
        try:
            payload = {
                "cells": {n: c.to_dict() for n, c in self.cells.items()},
                "health": {n: h.to_dict() for n, h in self.health.items()},
            }
            tmp = self._state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self._state_file)
        except Exception as e:  # noqa: BLE001
            logger.warning("[bandit] state save failed: %s", e)

    # --- Scoring ------------------------------------------------------------
    def predict_top_k(
        self,
        context: np.ndarray,
        candidates: list[str],
        k: int = 1,
    ) -> list[tuple[str, float, int]]:
        """Rank candidate providers by FGTS-VA score (best first)."""
        if not candidates:
            return []
        scored: list[tuple[str, float, int]] = []
        for name in candidates:
            cell = self.cells[name]
            total, _exploit, _bonus = score_cell(
                cell, context, self.mode, rng=_RNG, alpha=UCB_ALPHA
            )
            scored.append((name, total, cell.n_obs))
        # Desc by score; tie-break lowest n_obs to favor under-sampled arms.
        scored.sort(key=lambda x: (-x[1], x[2], x[0]))
        return scored[: max(1, k)]

    # --- Learning -----------------------------------------------------------
    def update_score(
        self,
        provider: str,
        context: np.ndarray,
        reward: float,
    ) -> None:
        cell = self.cells.get(provider)
        if cell is None:
            return
        cell.apply_update(context, reward)
        self._save()

    # --- Breaker / budget (router coordination helpers) ---------------------
    def is_available(self, provider: str, now: float | None = None) -> bool:
        h = self.health.get(provider)
        if h is None:
            return False
        if not h.allows_traffic():
            return False
        if h.is_cooldown_active(now):
            return False
        if h.is_budget_exhausted(BUDGET_EXHAUST_THRESHOLD):
            return False
        return True

    def record_success(self, provider: str) -> None:
        h = self.health.get(provider)
        if h is not None:
            h.record_success()
            self._consecutive_global_failures = 0
            self._save()

    def record_failure(self, provider: str, retry_after_s: float | None = None) -> None:
        h = self.health.get(provider)
        if h is not None:
            h.record_failure(retry_after_s)
            self._consecutive_global_failures += 1
            self._save()

    def consume_budget(self, provider: str, amount: float = 1.0) -> None:
        h = self.health.get(provider)
        if h is not None:
            h.consume_budget(amount)
            self._save()

    # --- Observability ------------------------------------------------------
    def status(self, provider_names: list[str]) -> list[dict[str, Any]]:
        """Per-provider state for the `search://providers` resource."""
        out: list[dict[str, Any]] = []
        for name in provider_names:
            h = self.health.get(name)
            c = self.cells.get(name)
            out.append(
                {
                    "name": name,
                    "state": h.state.value if h else BreakerState.CLOSED.value,
                    "available": self.is_available(name) if h else False,
                    "consecutive_failures": h._consecutive_failures if h else 0,
                    "budget_remaining": h.budget_remaining if h else None,
                    "n_obs": c.n_obs if c else 0,
                    "benchmark_prior": c.benchmark_prior if c else 0.0,
                    "sigma_sq_ewma": c.sigma_sq_ewma if c else 0.0,
                    "recent_reward_mean": c.recent_reward_mean if c else 0.0,
                    "mode": self.mode,
                }
            )
        return out


# Singleton — held at import time by the router. Providers are wired in
# `router.py` via `get_or_create(names)`.
_instance: BanditService | None = None


def get_or_create(provider_names: list[str]) -> BanditService:
    """Return the process-wide bandit singleton, creating on first call.

    The router imports this lazily so both tests and the live server share ONE
    posterior across all web_search calls.
    """
    global _instance
    if _instance is None:
        _instance = BanditService(provider_names)
    return _instance
