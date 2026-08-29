"""Pure FGTS-VA scoring + context + reward composition for the Search MCP.

Mirrors COELHO Nexus `domains/llm/rotator/bandit/domain.py`. No I/O, no state —
all functions are pure so they're trivially testable (Functional Core).

Modes: `fgts_va` (default), `ts`, `ucb` — selectable via env kill-switch in
`service._resolve_mode`.
"""
from __future__ import annotations

import time
from typing import Literal

import numpy as np

from .config import FGTS_VA, REWARDS
from .entities import CellState
from .params import CONTEXT_DIM, ERROR_CLASS_PENALTIES, TS_SCALE, UCB_ALPHA


Mode = Literal["ucb", "ts", "fgts_va"]


def theta_hat(cell: CellState) -> np.ndarray:
    """θ̂_a = A_a^-1 · b_a."""
    return np.linalg.solve(cell.A_a, cell.b_a)


def score_ucb(
    cell: CellState,
    context: np.ndarray,
    alpha: float = UCB_ALPHA,
) -> tuple[float, float, float]:
    """LinUCB (Li et al. ICML 2010)."""
    try:
        theta = theta_hat(cell)
    except np.linalg.LinAlgError:
        return (cell.benchmark_prior, cell.benchmark_prior, 0.0)
    exploit = float(context @ theta)
    A_inv_psi = np.linalg.solve(cell.A_a, context)
    explore = float(context @ A_inv_psi)
    if explore < 0:
        explore = 0.0
    bonus = alpha * float(np.sqrt(explore))
    return (exploit + bonus, exploit, bonus)


def score_ts(
    cell: CellState,
    context: np.ndarray,
    *,
    rng: np.random.Generator,
    scale: float = TS_SCALE,
) -> tuple[float, float, float]:
    """LinTS (Agrawal & Goyal ICML 2013); `explore` is L2 perturbation norm."""
    try:
        theta_mean = theta_hat(cell)
    except np.linalg.LinAlgError:
        return (cell.benchmark_prior, cell.benchmark_prior, 0.0)
    try:
        A_inv = np.linalg.inv(cell.A_a)
    except np.linalg.LinAlgError:
        return (float(context @ theta_mean), float(context @ theta_mean), 0.0)
    cov = (scale * scale) * A_inv
    cov = 0.5 * (cov + cov.T)
    try:
        theta_sampled = rng.multivariate_normal(theta_mean, cov, check_valid="ignore")
    except (np.linalg.LinAlgError, ValueError):
        theta_sampled = theta_mean
    score = float(context @ theta_sampled)
    perturbation = float(np.linalg.norm(theta_sampled - theta_mean))
    return (score, float(context @ theta_mean), perturbation)


def score_fgts_va(
    cell: CellState,
    context: np.ndarray,
    *,
    rng: np.random.Generator,
    sigma_min_sq: float = FGTS_VA.sigma_min_sq,
    feel_good_beta: float = FGTS_VA.feel_good_beta,
) -> tuple[float, float, float]:
    """FGTS-VA (NeurIPS 2025, arXiv:2511.02123): per-arm σ̂² replaces fixed scale²; feel-good β·√(ψᵀA^-1ψ) adds optimism."""
    try:
        theta_mean = theta_hat(cell)
    except np.linalg.LinAlgError:
        return (cell.benchmark_prior, cell.benchmark_prior, 0.0)
    sigma_sq = max(float(sigma_min_sq), float(cell.sigma_sq_ewma))
    try:
        A_inv = np.linalg.inv(cell.A_a)
    except np.linalg.LinAlgError:
        return (float(context @ theta_mean), float(context @ theta_mean), 0.0)
    cov = sigma_sq * A_inv
    cov = 0.5 * (cov + cov.T)
    try:
        theta_sampled = rng.multivariate_normal(theta_mean, cov, check_valid="ignore")
    except (np.linalg.LinAlgError, ValueError):
        theta_sampled = theta_mean
    exploit = float(context @ theta_sampled)
    bonus = 0.0
    if feel_good_beta > 0.0:
        try:
            A_inv_psi = np.linalg.solve(cell.A_a, context)
            explore_raw = float(context @ A_inv_psi)
            if explore_raw < 0.0:
                explore_raw = 0.0
            bonus = float(feel_good_beta) * float(np.sqrt(explore_raw))
        except np.linalg.LinAlgError:
            bonus = 0.0
    return (exploit + bonus, exploit, bonus)


def score_cell(
    cell: CellState,
    context: np.ndarray,
    mode: Mode,
    *,
    rng: np.random.Generator,
    alpha: float = UCB_ALPHA,
) -> tuple[float, float, float]:
    if mode == "fgts_va":
        return score_fgts_va(cell, context, rng=rng)
    if mode == "ts":
        return score_ts(cell, context, rng=rng)
    return score_ucb(cell, context, alpha=alpha)


def make_context_vector(
    *,
    query: str = "",
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = False,
    time_now: float | None = None,
    recent_failure_rate: float = 0.0,
) -> np.ndarray:
    """Compact 9-dim request context shared across all provider arms.

    Features:
      0  intercept (1.0)
      1  log1p(query length), log-2 normalized
      2  log1p(max_results) / log(20)
      3  advanced-depth flag
      4  include_answer flag
      5  sin(2π·hour/24) — 23:00 and 00:00 adjacent
      6  cos(2π·hour/24)
      7  weekday / 6
      8  recent_failure_rate (clamped 0..1) — global provider-health signal
    """
    v = np.zeros(CONTEXT_DIM, dtype=np.float64)
    v[0] = 1.0
    v[1] = float(np.log1p(max(0, len(query))) / np.log(100.0))
    v[2] = float(np.log1p(max(1, min(20, max_results))) / np.log(21.0))
    v[3] = 1.0 if search_depth == "advanced" else 0.0
    v[4] = 1.0 if include_answer else 0.0
    ts = time_now if time_now is not None else time.time()
    tm = time.gmtime(ts)
    hour_frac = (tm.tm_hour + tm.tm_min / 60.0) / 24.0
    v[5] = float(np.sin(2 * np.pi * hour_frac))
    v[6] = float(np.cos(2 * np.pi * hour_frac))
    v[7] = float(tm.tm_wday / 6.0)
    v[8] = float(max(0.0, min(1.0, recent_failure_rate)))
    return v


def compose_reward(
    *,
    success: bool,
    results_count: int = 0,
    latency_s: float | None = None,
    expected_latency_s: float | None = None,
    answer_present: bool = False,
    error_class: str | None = None,
    fusion_survival: float = 0.0,
    tidiness: float = 0.0,
) -> float:
    """Scalar reward in ~[-0.8, +1.0]; failure path driven by error_class penalties.

    Success path weights (`REWARDS`) reward quality: result yield, latency
    ratio, answer production, and — new — the fusion-survival agreement and
    content-tidiness quality signals (docs/ROUTING.md §7). `fusion_survival`
    and `tidiness` are 0..1 and default 0 when a request wasn't fused (the
    single-provider path pays only the quality floor).
    """
    if not success:
        return float(
            ERROR_CLASS_PENALTIES.get(error_class or "unknown", ERROR_CLASS_PENALTIES["unknown"])
        )
    r = REWARDS.success
    # Result yield: 0..~5+ results → 0..~1 (log compression).
    if results_count > 0:
        yield_signal = float(np.log1p(min(20, results_count)) / np.log1p(20))
        r += REWARDS.results * yield_signal
    if latency_s is not None and expected_latency_s and expected_latency_s > 0:
        ratio = float(latency_s) / float(expected_latency_s)
        lat_signal = max(-2.0, min(2.0, 1.0 - ratio))
        r += REWARDS.latency * (lat_signal / 2.0)
    if answer_present:
        r += REWARDS.answer
    # Quality terms: both 0..1, averaged before the weight (quality-first).
    r += REWARDS.quality * ((float(fusion_survival) + float(tidiness)) / 2.0)
    return r
