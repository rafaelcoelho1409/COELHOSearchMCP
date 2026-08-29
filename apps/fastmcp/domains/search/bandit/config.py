"""FGTS-VA + reward config for the Search MCP bandit.

Mirrors COELHO Nexus `domains/llm/rotator/bandit/config.py`. FGTS-VA is the
SOTA base (NeurIPS 2025, arXiv:2511.02123): variance-aware feel-good Thompson
sampling — per-arm EWMA noise σ̂² replaces the fixed TS scale², and a
feel-good optimism bonus β·√(ψᵀA⁻¹ψ) is added to the sampled score.

Env kill-switches (mirror Nexus `_resolve_mode`):
  SEARCH_BANDIT_MODE={ucb,ts,fgts_va} > SEARCH_DISABLE_FGTS_VA=1 (→ts) > default fgts_va.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FGTSVAConfig:
    """FGTS-VA (NeurIPS 2025, arXiv:2511.02123): per-arm σ̂² replaces fixed scale²; feel-good β adds bonus β·√(ψᵀA^-1ψ)."""

    sigma_init_sq: float = 0.25  # (0.5)² — matches compose_reward dynamic range
    sigma_min_sq: float = 0.04  # exploration floor
    var_alpha: float = 0.1  # EWMA half-life ~7 obs
    feel_good_beta: float = 0.1  # 0.0 → pure variance-aware LinTS


@dataclass(frozen=True, slots=True)
class RewardWeights:
    """Sums to ~1.0 when all signals present. Quality-focused success signals."""

    success: float = 0.30
    results: float = 0.25
    latency: float = 0.20
    answer: float = 0.25


FGTS_VA = FGTSVAConfig()
REWARDS = RewardWeights()
