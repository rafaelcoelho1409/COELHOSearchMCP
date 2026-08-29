# COELHO Search MCP — Routing Strategy (FGTS-VA lineage)

> Compact reference for implementing the SOTA routing algorithms. Pair with
> `docs/QUOTA.md` (provider capacity budgets) and `docs/CODE-CONVENTIONS.md`.
> Source: deep research into COELHO Nexus FGTS-VA rotator + Aug 2026 SOTA
> (bandits, circuit breakers, multi-provider routing).

## 1. The goal

Pick the **best-quality provider for each request** (main feature), honoring:

1. **Recurring-monthly-quota providers always come before one-time/pinned banks.**
   A provider with a monthly-refilling budget is prioritized; a "pinned" provider
   (one-time request count, then credit card) is used only as **fallback**.
2. **Fail-fast**: if the chosen provider fails (quota/network/timeout), route to the
   next best provider immediately — never wait out the full timeout of a dead arm.
3. Learn online (no training set): quality + latency + error feedback updates a
   persistent, contextual **bandit posterior** per provider.

## 2. Current implementation (done)

Router lives in `apps/fastmcp/domains/search/router.py`. Default `auto` order
(**quality-first, recurring before one-time**):

```python
router = SearchRouter([
    linkup,     # 1. recurring, 92% SimpleQA (#1 answer)          -> BEST QUALITY
    you,        # 2. recurring, 91% SimpleQA + livecrawl
    exa,        # 3. recurring, top AIMultiple relevance (14.39)
    geekflare,  # 4. recurring, grounded answer
    tavily,     # 5. recurring, answer + live balance
    tinyfish,   # 6. unmetered (free on every plan, 30 RPM), no answer
    firecrawl,  # 7. one-time bank (1K cr), #2 AIMultiple (14.58)
    serper,     # 8. one-time bank (2.5K), fast Google SERP
    jina,       # 9. one-time token bank
    serpapi,    # 10. recurring but LOWEST quality (~12.28 AIMultiple)
])
```

`SearchRouter` (current features):
- `PROVIDERS` priority list; `search()` dispatches pinned name or `auto`.
- `_search_auto()`: iterate `available()`, on `ProviderQuotaExceeded` → cooldown
  the arm (honor `retry_after_s`, else 60s) + fail over to next.
- `available()`: skips arms on cooldown.
- On non-quota errors (network/parse) → log + fail over (no cooldown).
- `search://providers` resource + `usage` tool expose per-provider state/credits.

## 3. The FGTS-VA algorithm (provenance & model)

**FGTS-VA = Variance-Aware Feel-Good Thompson Sampling for Contextual Bandits**
(Xuheng Li & Quanquan Gu, NeurIPS 2025, arXiv:2511.02123).

This is the SOTA base for LLM/provider selection in Nexus and is the model we
build on here. Per arm `a` (per provider):

- Contextual linear reward: `reward = θ_aᵀ·ψ(x)` with Gaussian posterior over `θ_a`.
- **Variance-aware**: replace fixed sampling scale² with per-arm EWMA noise
  `σ̂²`. Posterior sampler: `θ̃ ~ N(θ̂_a, σ̂²·A_a⁻¹)`.
- **Feel-good optimism bonus**: `β·√(ψᵀA_a⁻¹ψ)` added to sampled score.
- Update (order matters): residual from PRE-update θ̂ warms `σ²_ewma`, then
  posterior advance with forgetting (`A ← (1-γ)A + ψψᵀ`, `b ← (1-γ)b + r·ψ`).

Nexus reference (`domains/llm/rotator/`):
- `bandit/domain.py` — `score_fgts_va`, `score_ucb`, `score_ts`, `make_context_vector`.
- `bandit/entities.py` — `CellState` (A_a, b_a, n_obs, benchmark_prior, sigma_sq_ewma).
- `bandit/service.py` — `predict_top_k`, `update`, `try_reserve` (Redis persistence).
- `chain/service.py` — fail-fast cascade over ranked arms + `_ARM_COOLDOWN_S`
  on 429 + `allowed_fails_policy` circuit breaker + per-provider in-flight caps.

## 4. SOTA gaps to close for Search MCP (implementation plan)

FGTS-VA assumes **stochastic, ~stationary** rewards. Search-MCP breaks that with
**adversarial exhaustion + disjoint finite quotas**. Three upgrades, in priority:

### 4.1 Circuit breaker state machine (HIGH leverage, LOW risk)
Research consensus (TrueFoundry, OneUptime, AppScale, 2026):
CLOSED → OPEN → HALF-OPEN. Trip after ~5 consecutive failures, cooldown ~60s,
then ONE half-open probe request; success closes it, failure re-opens.
- Replace cooldown-only with a 3-state breaker per provider.
- Effect: a dead provider costs one fast rejection → clean failover, no cascade.
- THIS is the core of the "fail-fast engine."

### 4.2 Sliding-window / discounted reward forgetting (non-stationarity)
Since rewards can **abruptly** change (exhaustion, outage), use SW-TS or
discounted TS (Garivier & Moulines). Today `FORGETTING_GAMMA=0.01` is a slow
static EWMA; make it windowed/discounted so a hard breakpoint (quota hit) demotes
the arm fast — the bandit itself fails fast on quality.

### 4.3 Quota as a knapsack constraint (BwK) — budget pre-filter
Don't let the bandit discover exhaustion the slow way (burns a request on a dead
arm). Instead, at the router boundary:
- Track each provider's **remaining budget** (Tavily live balance; others via
  `usage` + static ceilings from `docs/QUOTA.md`).
- **Exclude arms with remaining ≈ 0 from `available()` BEFORE scoring** (BwK
  hard filter). This preserves the quality-first ordering while never throwing
  real requests at an exhausted provider.
- Optional scoring touch: prefer high reward AND abundant remaining quota
  (UCB/cost-ratio style — "Bandits with Knapsacks," Badanidiyuru et al.).

## 5. Answer-aware routing (include_answer=True)

The reward signal differs when the user wants a synthesized answer vs raw links.
For `include_answer=True`, prefer answer-capable providers first:
**Linkup → You.com → Tavily → Geekflare** (each returns an LLM-grounded answer).
Raw-link providers (TinyFish, Serper, Jina, Firecrawl, SerpApi) serve the
non-answer path.

## 6. Intent / freshness awareness

- **Freshness-sensitive queries** (news, current events): prefer live-web
  providers — Linkup, You, Tavily, Geekflare. **Exa is weak here** (24% FreshQA;
  neural index goes stale). Exa shines for **semantic discovery / research**.
- This can be an opt-in `intent` hint or a lightweight heuristic; DB-quality
  ordering above already biases toward answer/live providers.

## 7. Why NOT the alternatives (research findings)

- RouteLLM / NotDiamond / Router-R1 / BaRP / Azure Model Router: **learned
  classifier/RL routers** — need preference-pair training data, and optimize
  "cheap vs strong" WITHOUT quota semantics. We have no training set and our
  constraint (disjoint quotas) is not their objective.
- Exp3/EXP4 (adversarial): robust to adversaries but high regret in your mostly-
  stochastic setting; keep as pure fallback only.
- **A contextual bandit is the right class; FGTS-VA is the SOTA base.** The
  three upgrades (breaker + sliding-window + BwK pre-filter) make it SOTA *for
  this specific problem*.
