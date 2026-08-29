"""Per-provider state for the Search MCP bandit router.

Mirrors COELHO Nexus `domains/llm/rotator/bandit/entities.py` (`CellState`) and
adds the SOTA router health state from `docs/ROUTING.md` §4:

- **CellState** — FGTS-VA per-arm linear-bandit posterior (A_a, b_a, n_obs,
  benchmark_prior, sigma_sq_ewma) plus a bounded sliding-window reward history.
- **ProviderHealth** — circuit-breaker state machine (CLOSED/OPEN/HALF-OPEN)
  + cooldown + BwK remaining-budget ledger.

Both are JSON-serializable for optional file persistence (no Redis in this MCP).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from .config import FGTS_VA
from .params import (
    BUDGET_EXEMPT,
    CONTEXT_DIM,
    FORGETTING_GAMMA,
    PROVIDER_BUDGET_CAP,
    RIDGE_LAMBDA,
)


logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    """Three-state circuit breaker (docs/ROUTING.md §4.1)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CellState:
    """Per-arm FGTS-VA posterior; JSON-serializable for persistence."""

    provider: str
    A_a: np.ndarray
    b_a: np.ndarray
    n_obs: int
    last_updated: float
    benchmark_prior: float
    sigma_sq_ewma: float = field(default=FGTS_VA.sigma_init_sq)
    # Sliding-window of recent rewards (bounded) — powers non-stationarity
    # observability; the posterior itself is discounted via FORGETTING_GAMMA.
    recent_rewards: deque[float] = field(default_factory=lambda: deque(maxlen=100))

    @classmethod
    def fresh(cls, provider: str, benchmark_prior: float) -> "CellState":
        prior = max(0.0, min(1.0, float(benchmark_prior)))
        # Higher prior → tighter posterior; below 0.1 → ridge-only "unknown".
        confidence = max(0.1, prior)
        A_a = (RIDGE_LAMBDA / confidence) * np.eye(CONTEXT_DIM, dtype=np.float64)
        theta_init = (prior / CONTEXT_DIM) * np.ones(CONTEXT_DIM, dtype=np.float64)
        b_a = A_a @ theta_init
        return cls(
            provider=provider,
            A_a=A_a,
            b_a=b_a,
            n_obs=0,
            last_updated=time.time(),
            benchmark_prior=prior,
            sigma_sq_ewma=FGTS_VA.sigma_init_sq,
            recent_rewards=deque(maxlen=100),
        )

    @property
    def recent_reward_mean(self) -> float:
        if not self.recent_rewards:
            return self.benchmark_prior
        return float(np.mean(list(self.recent_rewards)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "A_a": self.A_a.tolist(),
            "b_a": self.b_a.tolist(),
            "n_obs": self.n_obs,
            "last_updated": self.last_updated,
            "benchmark_prior": self.benchmark_prior,
            "sigma_sq_ewma": self.sigma_sq_ewma,
            "recent_rewards": list(self.recent_rewards),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CellState":
        """Re-init from benchmark_prior on CONTEXT_DIM drift (prevents matmul failure)."""
        A_a = np.asarray(d["A_a"], dtype=np.float64)
        b_a = np.asarray(d["b_a"], dtype=np.float64)
        expected = (CONTEXT_DIM, CONTEXT_DIM)
        if A_a.shape != expected or b_a.shape != (CONTEXT_DIM,):
            logger.warning(
                "[bandit] cell dim drift for provider %r: stored A_a %s vs "
                "expected %s; re-initializing from benchmark_prior",
                d.get("provider"),
                A_a.shape,
                expected,
            )
            return cls.fresh(d["provider"], float(d.get("benchmark_prior", 0.0)))
        w = deque(maxlen=100)
        w.extend(float(x) for x in d.get("recent_rewards", []))
        return cls(
            provider=d["provider"],
            A_a=A_a,
            b_a=b_a,
            n_obs=int(d.get("n_obs", 0)),
            last_updated=float(d.get("last_updated", time.time())),
            benchmark_prior=float(d.get("benchmark_prior", 0.0)),
            sigma_sq_ewma=float(d.get("sigma_sq_ewma", FGTS_VA.sigma_init_sq)),
            recent_rewards=w,
        )

    def apply_update(
        self,
        context: np.ndarray,
        reward: float,
        *,
        gamma: float = FORGETTING_GAMMA,
        var_alpha: float = FGTS_VA.var_alpha,
    ) -> None:
        """Order matters: σ² uses PRE-update θ̂ (unbiased residual) before advance."""
        try:
            theta_pre = np.linalg.solve(self.A_a, self.b_a)
            residual = float(reward) - float(context @ theta_pre)
            self.sigma_sq_ewma = (
                1.0 - var_alpha
            ) * self.sigma_sq_ewma + var_alpha * (residual * residual)
        except np.linalg.LinAlgError:
            pass
        keep = 1.0 - gamma
        self.A_a = keep * self.A_a + np.outer(context, context)
        self.b_a = keep * self.b_a + reward * context
        self.n_obs += 1
        self.recent_rewards.append(float(reward))
        self.last_updated = time.time()


@dataclass
class ProviderHealth:
    """Circuit breaker + cooldown + BwK budget for a single provider.

    - Breaker: CLOSED → OPEN on `fail_threshold` consecutive failures; after
      `cooldown_s`, allow exactly one HALF_OPEN probe; success closes, failure
      re-opens (docs/ROUTING.md §4.1).
    - Cooldown: explicit Retry-After window (e.g. quota 429 with a hint).
    - Budget: remaining BwK capacity; unmetered providers (TinyFish) exempt.
    """

    provider: str
    fail_threshold: int
    cooldown_s: float
    probe_timeout_s: float = 10.0
    _state: BreakerState = BreakerState.CLOSED
    _consecutive_failures: int = 0
    _cooldown_until: float = 0.0
    _half_open_attempt: float = 0.0
    _consecutive_successes: int = 0
    _budget_remaining: float | None = None

    def __post_init__(self) -> None:
        # Seed BwK budget from static capacity; None only if unmetered/unknown.
        cap = PROVIDER_BUDGET_CAP.get(self.provider, 0)
        if self.provider in BUDGET_EXEMPT or cap <= 0:
            self._budget_remaining = None  # unmetered — never pruned
        else:
            self._budget_remaining = float(cap)

    # --- BwK budget ---------------------------------------------------------
    @property
    def budget_remaining(self) -> float | None:
        return self._budget_remaining

    def consume_budget(self, amount: float = 1.0) -> None:
        if self._budget_remaining is not None:
            self._budget_remaining -= amount

    def is_budget_exhausted(self, threshold: int = 1) -> bool:
        """BwK pre-filter: limit-scaled capacity spent (exempt arms never pruned)."""
        if self._budget_remaining is None:
            return False
        return self._budget_remaining < threshold

    # --- Circuit breaker -----------------------------------------------------
    @property
    def state(self) -> BreakerState:
        now = time.monotonic()
        # Lazy CLOSED→HALF_OPEN transition once the OPEN cooldown expires.
        if self._state is BreakerState.OPEN and now >= self._cooldown_until:
            self._state = BreakerState.HALF_OPEN
            self._half_open_attempt = now
        # A HALF_OPEN probe that never resolves within the timeout re-opens.
        if self._state is BreakerState.HALF_OPEN and self._half_open_attempt:
            if now - self._half_open_attempt > self.probe_timeout_s:
                self._state = BreakerState.OPEN
                self._cooldown_until = now + self.cooldown_s
        return self._state

    def allows_traffic(self, now: float | None = None) -> bool:
        """Whether a request may be dispatched to this provider right now."""
        st = self.state
        if st is BreakerState.OPEN:
            return False
        if st is BreakerState.HALF_OPEN:
            # Allow exactly ONE concurrent probe at a time.
            return True
        return True

    def is_half_open(self) -> bool:
        return self.state is BreakerState.HALF_OPEN

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._consecutive_successes += 1
        if self.state is BreakerState.HALF_OPEN:
            # Probe succeeded → close the circuit.
            self._state = BreakerState.CLOSED
            self._consecutive_successes = 0
            self._half_open_attempt = 0.0
        # CLA: reset cooldown fully on success.
        self._cooldown_until = 0.0

    def record_failure(self, retry_after_s: float | None = None) -> None:
        self._consecutive_successes = 0
        if self.state is BreakerState.HALF_OPEN:
            # Probe failed → re-open for another full cooldown.
            self._state = BreakerState.OPEN
            self._half_open_attempt = 0.0
            self._cooldown_until = time.monotonic() + (
                retry_after_s if retry_after_s is not None else self.cooldown_s
            )
            return
        self._consecutive_failures += 1
        if retry_after_s is not None:
            # Explicit Retry-After → cooldown (even before trip threshold).
            self._cooldown_until = time.monotonic() + retry_after_s
        if self._consecutive_failures >= self.fail_threshold:
            self._state = BreakerState.OPEN
            self._cooldown_until = time.monotonic() + (
                retry_after_s if retry_after_s is not None else self.cooldown_s
            )

    def is_cooldown_active(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return self._cooldown_until > now

    # --- Persistence ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "fail_threshold": self.fail_threshold,
            "cooldown_s": self.cooldown_s,
            "probe_timeout_s": self.probe_timeout_s,
            "state": self._state.value,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "cooldown_until": self._cooldown_until,
            "half_open_attempt": self._half_open_attempt,
            "budget_remaining": self._budget_remaining,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProviderHealth":
        h = cls(
            provider=d["provider"],
            fail_threshold=int(d.get("fail_threshold", 5)),
            cooldown_s=float(d.get("cooldown_s", 60.0)),
            probe_timeout_s=float(d.get("probe_timeout_s", 10.0)),
        )
        h._state = BreakerState(d.get("state", "closed"))
        h._consecutive_failures = int(d.get("consecutive_failures", 0))
        h._consecutive_successes = int(d.get("consecutive_successes", 0))
        h._cooldown_until = float(d.get("cooldown_until", 0.0))
        h._half_open_attempt = float(d.get("half_open_attempt", 0.0))
        br = d.get("budget_remaining")
        h._budget_remaining = None if br is None else float(br)
        return h
