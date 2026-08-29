"""Bandit hyperparameters for the Search MCP provider router.

Mirrors COELHO Nexus `domains/llm/rotator/bandit/params.py` (FGTS-VA lineage)
with the three SOTA upgrades from `docs/ROUTING.md` §4:

1. **Circuit breaker** — per-provider CLOSED/OPEN/HALF-OPEN (trip, cooldown, probe).
2. **Discounted / sliding-window forgetting** — FORGETTING_GAMMA demotes an arm
   fast after an abrupt quality breakpoint (outage / quota hit).
3. **BwK budget pre-filter** — static capacity ceilings per provider from
   `docs/QUOTA.md`, used to exclude exhausted arms before scoring.

Everything is a loose module constant (no frozen-dataclass GROUP here) because
these are one-off tunables mirroring Nexus's params.py, not a grouped concept.
"""
from __future__ import annotations


def _env_int(name: str, default: int) -> int:
    import os

    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    import os

    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Context / posterior ---------------------------------------------------
# Request-level context shared across all provider arms; each arm has its own
# linear posterior θ_a over these features. Small enough to learn from sparse
# per-provider observations.
CONTEXT_DIM = 9

UCB_ALPHA = 0.5
TS_SCALE = 0.5
# Ridge on A_a + weak prior θ̂_a → 0.
RIDGE_LAMBDA = 1.0
# γ=0.05: stronger recency than Nexus (0.01) so a hard failure (quota hit /
# outage) demotes the arm in ~20 obs instead of ~100 — the non-stationarity fix.
FORGETTING_GAMMA = _env_float("SEARCH_BANDIT_GAMMA", 0.05)

# --- Circuit breaker (docs/ROUTING.md §4.1) ---------------------------------
BREAKER_FAIL_THRESHOLD = _env_int("SEARCH_BREAKER_FAIL_THRESHOLD", 5)
BREAKER_COOLDOWN_S = _env_float("SEARCH_BREAKER_COOLDOWN_S", 60.0)
# How long a HALF-OPEN probe may live before it must resolve (re-open if stale).
BREAKER_PROBE_TIMEOUT_S = _env_float("SEARCH_BREAKER_PROBE_TIMEOUT_S", 10.0)

# --- Error-class penalties (reward on failure path) -------------------------
# Strong enough to flip ranking after a few consecutive hard failures.
ERROR_CLASS_PENALTIES: dict[str, float] = {
    "rate_limit":     -0.10,
    "timeout":        -0.60,
    "server_error":   -0.50,
    "auth_error":     -0.80,
    "schema_invalid": -0.40,
    "content_filter": -0.20,
    "unknown":        -0.40,
}

# Expected search latency (s) used to normalize the latency reward signal.
# Providers slower than this are penalized on the reward path.
EXPECTED_LATENCY_S = 2.0

# --- BwK budget ceilings (docs/QUOTA.md) ------------------------------------# Static free-tier capacity per provider; used as the knapsack budget when the
# provider has no live `search_credits_remaining()` endpoint (→ None). Values
# are best-effort monthly figures; Tier 1 recurring > Tier 2 one-time banks.
PROVIDER_BUDGET_CAP: dict[str, int] = {
    "linkup":    4000,
    "you":       3000,
    "exa":       1200,
    "geekflare":  250,
    "tavily":    1000,
    "tinyfish":     0,  # unmetered — no budget, never excluded
    "firecrawl":  750,
    "serper":    2500,
    "jina":      1000,
    "serpapi":    250,
}
# Remaining below this still counts as "usable but nearly spent" → excluded.
# TinyFish (0 cap) is exempt: it must never be pruned.
BUDGET_EXHAUST_THRESHOLD = 1
# Providers considered unmetered / exempt from BwK pruning.
BUDGET_EXEMPT = frozenset({"tinyfish"})

# --- Warm-start benchmark priors (docs/ROUTING.md §2 ordering) ---------------# Quality-first, recurring-before-one-time. Seeds each arm's `benchmark_prior`
# so the router behaves correctly BEFORE any learning happens (mirrors Nexus
# benchmarks warm-start). Range roughly [0,1].
PROVIDER_BENCHMARK_PRIOR: dict[str, float] = {
    "linkup":    0.92,
    "you":       0.91,
    "exa":       0.85,
    "geekflare": 0.80,
    "tavily":    0.78,
    "tinyfish":  0.55,
    "firecrawl": 0.82,
    "serper":    0.72,
    "jina":      0.60,
    "serpapi":   0.40,
}
# Arms answering `include_answer=True` (Tier 1 recurring that return an LLM
# answer). Used by answer-aware routing (docs/ROUTING.md §5). TinyFish is the
# sole unmetered arm but returns no answer → excluded here.
ANSWER_CAPABLE = frozenset({"linkup", "you", "tavily", "geekflare"})
