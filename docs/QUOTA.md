# COELHO Search MCP — Provider Quota Reference (Aug 2026)

> Source of truth for per-provider capacity → used by the BwK budget pre-filter
> (`docs/ROUTING.md` §4.3) and the `usage` tool fallbacks. Figures are the best
> available Aug 2026 free-tier data; treat as ±20% where noted.
>
> **Key rule: recurring-monthly-quota providers are prioritized; one-time/pinned
> banks are fallback.** Tier 0/1 = recurring or unmetered = primary; Tier 2 =
> one-time bank = fallback; Tier 3 = last resort.

## Provider roster — 10 providers (all wired into the unified MCP)

| # | Provider | Tier | Replenishment | Capacity (free) | No card? | Answer? | Live balance? |
|---|---|---|---|---|---|---|---|
| 1 | **linkup** | T1 | recurring | ~4K/mo (≈$20/mo; older srcs say €5/mo) | yes | ✅ 92% SimpleQA | no |
| 2 | **you** | T1 | recurring | 100/day (~3K/mo) **or** $100 one-time credit *(conflicting)* | yes | ✅ 91% | no |
| 3 | **exa** | T1 | recurring | 1K–1.4K/mo | yes | ✅ | no |
| 4 | **geekflare** | T1 | recurring | 500 cr/mo, 2/search ≈ **250/mo** | **yes** | ✅ | no |
| 5 | **tavily** | T1 | recurring | 1K/mo | **no (card)** | ✅ | ✅ (live, 670) |
| 6 | **tinyfish** | T0 | **unmetered** | free on EVERY plan, 30 RPM search | yes | ❌ (no answer) | no |
| 7 | **firecrawl** | T2 | one-time bank | 1K cr/mo *(also cited as 500)* | yes | ❌ | no |
| 8 | **serper** | T2 | one-time bank | 2.5K queries | yes | ❌ (raw JSON) | no |
| 9 | **jina** | T2 | one-time token bank | 10M tokens (~1K searches) | yes | ❌ | no |
| 10 | **serpapi** | T1* | recurring | 250/mo | yes | ✅ | no |

_* SerpApi is recurring (250/mo) but LOWEST quality (~12.28 AIMultiple, slowest
~5.5s) — placed last in routing despite its tier._

## Totals (recurring/unmetered vs one-time)

- **Recurring + unmetered (Tier 0/1):** ~8,500–10,150 searches/mo + **TinyFish
  unlimited**. ← primary budget
- **One-time banks (Tier 2):** Serper 2,500 + Firecrawl ~500–1K + Jina ~1K. ←
  fallback budget

## Confidence caveats (±20%)

- Firecrawl "1,000 one-time" vs "500/mo" — conflicting sources → treat as
  one-time bank ~500–1K.
- You.com "100/day" vs "$100 one-time credit" — conflicting → treat as recurring
  with a hard annual cap.
- Jina is token-based (10M tokens), search cost ~10K tokens/query → ~1K searches.
- Linkup "$20/mo" is best-verified; older sources say €5/mo.
- Tavily is the ONLY provider exposing a live balance endpoint (currently 670
  and dropping). All others report `None` → use these static ceilings as the
  BwK capacity fallback.

## BwK budget bookkeeping (implementation note)

For each provider maintain `remaining ≈ static_capacity − cumulative_usage`
(live when available via `search_credits_remaining()`). At route time:

```python
def available():  # BwK pre-filter before bandit scoring
    return [p for p in providers
            if not on_cooldown(p)      # circuit breaker not OPEN
            and remaining(p) > 0]      # budget not exhausted
```

Exclude arms with `remaining <= 0` so the quality-first router never throws real
requests at an exhausted provider.
