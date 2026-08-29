# COELHO Search MCP — Code Conventions & Roadmap

> Authored guardrail for the FastMCP server. Every tool/resource/prompt/provider
> generated in this repo MUST conform to this shape. This is the mechanism that
> keeps AI-generated code inside a structure **you** designed — review against
> this, not against "does it run."
>
> Sibling doc: COELHO Nexus `docs/CODE-CONVENTIONS.md` (the shared rulebook this
> project inherits). Read that first; this file adds only what is Search-MCP-specific.

## TL;DR

- One **bounded context** per MCP server capability. `search/` is the only domain today.
- MCP's three primitives each get their own folder: `tools/`, `resources/`, `prompts/`.
- **Providers are adapters inside the domain**, not sibling domains, not `infra/` (yet).
- Per-tool/provider 5-file split: **config → schemas → domain → service → register**.
- Pure logic lives in `domain.py` as **free functions**. Stateful I/O lives in **classes** in `service.py`.
- Every capability is registered via a `register(mcp)` function; `server.py` composes them.
- Cross-cutting concerns (routing, quota) live at the domain root (`router.py`), not in tools.

---

## 1. Repository / domain layout

```text
apps/fastmcp/
├── server.py                    # root: creates FastMCP, calls domain.register(mcp)
└── domains/
    └── search/                  # THE bounded context (single domain today)
        ├── __init__.py
        ├── server.py            # compose register(): tools + resources + prompts
        ├── schemas.py           # shared provider-agnostic boundary types
        ├── router.py            # coordination: priority + cooldown + failover
        ├── tools/               # MCP ACTIONS  (web_search, usage)
        │   ├── __init__.py      #   register(mcp) aggregates
        │   ├── web_search.py
        │   └── usage.py
        ├── resources/           # MCP CONTEXT reads (search://providers)
        │   └── __init__.py
        ├── prompts/             # MCP reusable templates (/search_agent)
        │   └── __init__.py
        └── providers/           # ADAPTERS (ports & adapters) — domain-internal
            ├── __init__.py
            ├── base.py          # BaseSearchProvider protocol
            ├── exceptions.py    # ProviderQuotaExceeded (cross-provider signal)
            └── tavily/
                ├── __init__.py  # exports `tavily` singleton adapter
                ├── config.py    # frozen-dataclass
                ├── schemas.py   # (if provider-specific types exist)
                ├── domain.py    # PURE: normalize raw → SearchResult
                └── service.py   # I/O: AsyncTavilyClient + TavilyClient class
```

### Rules

- A **bounded context** is a capability the agent cares about (`search`), NOT a vendor
  (`tavily`). Vendors are `providers/<name>/` inside one context.
- Keep `providers/` inside `search/`. Only promote to a shared `infra/providers/`
  (like Nexus `infra/`) when a **second** domain consumes the same adapters. Do not
  promote preemptively — premature abstraction is an anti-pattern.
- `tools/`, `resources/`, `prompts/` contain ONLY MCP-surface components.
  `router.py`, `schemas.py`, and `providers/` are coordination/adapters, not MCP
  components, so they live at the domain root beside those folders.

---

## 2. The 5-file tool/provider template

Each tool (and each provider adapter) follows the same shape as Nexus.

| File | Role | Shape |
|---|---|---|
| `config.py` | tunables for one concept | frozen `@dataclass(frozen=True, slots=True)`, module-level singleton (e.g. `TAVILY`) |
| `schemas.py` | validation + LLM-visible boundary | Pydantic `BaseModel` |
| `domain.py` | **pure** parse/normalize — no I/O | **free functions** |
| `service.py` | async I/O + error mapping | **classes** (stateful) + thin functions |
| `tool.py` / `provider/__init__.py` | `register(mcp)` / adapter singleton | thin shell |

### `domain.py` — functional core (NO state)
- Stateless, deterministic, no I/O/network/logging/clocks/mutable globals.
- Free functions, e.g. `normalize_results(raw: list[dict]) -> list[SearchResult]`.
- **Do NOT wrap pure logic in classes.** If it has no `self`, it stays a function.
  This is the single most oversimplified "improvement" and it hurts testability.

### `service.py` — imperative shell (STATE OK)
- Async + httpx + error mapping live here.
- **Stateful orchestration belongs in a CLASS** that owns config + reused
  `httpx.AsyncClient` (connection pooling). E.g. `TavilyClient`.
- Adapters (`TavilyAdapter`) wrap the service class and satisfy `BaseSearchProvider`.

### Decision rule — method on a class vs free function
> If it needs `self` to hold state/config across calls → class method.
> If it is a stateless transformation → free function. Classes are not "neater by default."

---

## 3. Registration idiom

Every folder aggregates via `register(mcp)`; `server.py` never contains tool bodies.

```python
# tools/__init__.py
from fastmcp import FastMCP
from . import usage, web_search

def register(mcp: FastMCP) -> None:
    web_search.register(mcp)
    usage.register(mcp)
```

```python
# tools/web_search.py
def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def web_search(ctx: Context, query: str, ...) -> SearchResponse:
        # thin: build SearchInput -> router.search -> ToolError mapping at boundary
```

`server.py` composes the three:

```python
from . import prompts, resources, tools

def register(mcp: FastMCP) -> None:
    tools.register(mcp)      # (2)
    resources.register(mcp)  # (1)
    prompts.register(mcp)    # (1)
```

---

## 4. Cross-cutting: router, quota, failover

- `router.py` owns priority order + cooldown map + failover. It is the coordinator.
- Providers raise a **single** cross-provider exception: `ProviderQuotaExceeded`
  (from `providers/exceptions.py`). Each adapter maps its vendor error (e.g.
  `TavilyKeylessLimitError`) into that one signal. **Never leak vendor exceptions
  through `router`/`tools`.**
- New providers are appended to the router's provider list. To add Exa/Jina/Linkup:
  1. New `providers/<name>/` package implementing `BaseSearchProvider`.
  2. Map its quota/rate-limit errors to `ProviderQuotaExceeded(...)`.
  3. Append `...ProviderAdapter()` to the list in `router.py`.
  That's the whole integration — the `web_search` tool and schema do not change.

---

## 5. Provider-agnostic schemas

The agent sees ONE unified result shape. Do NOT fork per provider.

- `SearchInput` — least-common-denominator params all providers honor.
- `SearchInput.provider` — the selection switch. `"auto"` (default) → router picks
  by priority + failover; a specific name (`"tavily"`, `"exa"`, ...) pins that
  provider. Unknown/on-cooldown/quota-exhausted names fall back to `auto`.
- `SearchResult` — normalized title/url/content/score/raw_content. Vendor-specific
  extras stay in the adapter, never pollute the shared type.
- `SearchResponse` — includes `provider` tag for observability/quota attribution
  (tells the caller which engine actually served the request).

### Router dispatch

- `router.provider_names` — registered names, priority order.
- `router.search(req, ctx)` — reads `req.provider`; pinned names route
  directly, everything else goes through `_search_auto` (priority + failover).
- When a **pinned** provider is exhausted/on-cooldown, the router marks it for
  cooldown and falls back to `auto` rather than erroring.

---

## 6. Env / secrets

- Keys come from a K8s Secret via `secretMappings` in `k8s/helm/values.yaml`
  (`envName` → `key`), e.g. `TAVILY_API_KEY` → `tavily-api-key`.
- Provider `config.py` reads the key from env in `__post_init__`
  (`os.getenv("TAVILY_API_KEY", "")`). Empty → keyless/unavailable.
- Never hard-code keys, never log them.

---

## 7. Error handling at the boundary

- Convert provider errors to `ToolError` in the `@mcp.tool` body (or a thin wrapper).
- Guard `ctx.info`/`ctx.report_progress` so the tool works when no MCP session is live
  (direct/programmatic calls). Use the session-guard helper, not raw `ctx.info`.
- Distinguish **quota** (`ProviderQuotaExceeded` → failover) from **network**
  (surfaced, not retried by router).

---

## 8. Anti-patterns (what NOT to do)

- ❌ Naming a domain after a vendor (`domains/tavily/`) — a provider is an adapter.
- ❌ Prematurely extracting `providers/` to a shared root with one consumer.
- ❌ Wrapping pure `domain.py` functions in classes "for organization."
- ❌ Leaking vendor exceptions into `router`/`tools`.
- ❌ Adding provider-specific fields to the shared `SearchResult` schema.
- ❌ Putting tool bodies in `server.py` instead of `tools/<name>.py`.

---

## 9. Roadmap: next steps (Exa → Jina → Linkup → observability)

Phase order is deliberate — each step is additive and testable.

### Phase 3A — Exa provider (neural/semantic search)
1. `providers/exa/` with `config.py` (key: `EXA_API_KEY`), `domain.py` (normalize
   Exa results → shared `SearchResult`), `service.py` (`ExaClient` + adapter).
2. Confirm Exa's official SDK or raw httpx to `/search` (`https://api.exa.ai/search`).
3. Map Exa rate-limit/`429` → `ProviderQuotaExceeded`.
4. Append `exa` to `router.py` provider list (Tavily first, Exa second).
5. Add `EXA_API_KEY` → `exa-api-key` to `secretMappings`.

### Phase 3B — Jina provider (news/sReader + search) ✅
1. `providers/jina/` (`config.py` key `JINA_API_KEY`, `service.py` — `JinaClient`
   + `JinaAdapter` POST to `s.jina.ai/`, `domain.py` — **plain-text markdown
   parser**). Note: s.jina.ai returns numbered `[N] Title/URL Source/...` blocks
   in markdown, NOT JSON; `domain.parse_results` extracts blocks via regex.
2. Map `429`/`401`/`402`/`403` → `ProviderQuotaExceeded`; append to router.
3. Free tier = 100 RPM, ~10k tokens/search, no queryable balance (credits=None).

### Phase 3C — Linkup provider (deep research) ✅
1. `providers/linkup/` (`config.py` key `LINKUP_API_KEY`, `service.py` —
   `LinkupClient` POST to `/v1/search`, `domain.py` — normalizes both
   `searchResults` and `sourcedAnswer` shapes).
2. Honours `include_answer`: `sourcedAnswer` (answer + sources) when requested,
   else `searchResults` — Tavily-parity on answer summaries.
3. Map 402/429 → `ProviderQuotaExceeded`; free tier, no queryable balance
   (credits=None).

### Phase 3D — RRF merge (optional, cross-provider quality) — IDEA SAVED
> Status: **deferred** (algorithms implemented later). Design captured below.

**What it is:** Reciprocal Rank Fusion (RRF) merges the SAME query's results from
**multiple providers in parallel** into one harmonized list — as opposed to the
current design, which uses providers for **failover** (one at a time by priority).

**Why raw scores can't be averaged:** each provider ranks with its own metric and
they're not comparable (Tavily gives 0-1 scores; Exa/Jina/Linkup give none). RRF
ignores raw scores and uses only each result's **rank position** within its
provider list:

    score(url) = Σ over providers  1 / (rank_in_that_provider + k),   k = 60 (typical)

Results ranked high in MULTIPLE providers win (consensus ≈ relevance). RRF also
de-dupes URLs across providers by construction.

**Example:** `docs.djangoproject.com` ranked 1·2·3·1 across 4 providers scores
0.0642, while a page only Linkup ranks 2 scores 0.0161 → Django docs wins.

**Trade-offs (why it's opt-in, not default):**
- 4x per-query API cost (hits every provider)
- Waits for the slowest provider (latency)
- 4x content = heavy tokens (bad for small models like Qwen-27B)
- Adds a `merge`/`search_mode` footgun to the tool

**Recommended integration:** keep `auto` = cheap single-provider failover as the
default (optimal for the token-conscious small-model stack). Add RRF as an **opt-in
mode**, e.g. `web_search(merge="rrf")` or `provider="all"` for high-stakes /
deep-research queries. This mirrors Argus/Oracle: failover for default, RRF for
consensus-heavy research.

**Implementation sketch:** `router.merge_rrf(providers, req, ctx)` → run
`asyncio.gather` over all available providers → fuse by `score = Σ 1/(rank+k)` →
sort desc → return unified `SearchResponse` (dropping per-provider scores, which
are RRF scores, not provider scores). Add an RRF rank refinement step (Phase 6)
that reorders using the top fused result as a reranking query, per the Google
demo on combining generative and extractive search (a deterministic, no-additional-
API-cost version of Argus's Deep Hybrid Rank).

### Phase 3E — You.com provider (keyless daily quota) ✅
1. `providers/you/` (`config.py` key `YOUCOM_API_KEY`, `service.py` —
   `YouClient` + `YouAdapter` POST to `https://ydc-index.io/v1/search`,
   `domain.py` — normalizes `results.web[]` (and `results.news[]` fallback)).
2. Auth is `X-API-Key` (Optional on free tier). NOTE: the canonical host is the
   bare `ydc-index.io` (NO `api.` subdomain) — `api.you.com` 500s and
   `api.ydc-index.io` rejects the token. Quote-strip the key in `__post_init__`
   (a `YOUCOM_API_KEY="..."` .env value otherwise ships with literal quotes).
3. Map `429`/`402`/`403` → `ProviderQuotaExceeded`; free tier = 100 queries/day,
   no live balance endpoint (credits=None).
4. Append `you` to the router (5th in priority: tavily, exa, jina, linkup, you).

### Phase 3F — Serper provider (Google SERP index) ✅
1. `providers/serper/` (`config.py` key `SERPER_API_KEY`, `service.py` —
   `SerperClient` + `SerperAdapter` POST to `https://google.serper.dev/search`
   with `X-API-KEY` + `{"q", "num"}` body, `domain.py` — normalizes `organic[]`
   to `SearchResult` and pulls optional `answerBox` into `answer`).
2. Adds a GOOGLE-index source the pool otherwise lacks (Tavily/You are
   independent; Exa semantic; Jina/Linkup niche). Free tier = 2,500
   searches/month, no card; optional `answerBox` → Tavily/Serper answer parity.
3. Map `429`/`402`/`403` → `ProviderQuotaExceeded`; no live balance endpoint
   (credits=None).
4. Append `serper` to the router (6th: tavily, exa, jina, linkup, you, serper).

### Phase 3G — Firecrawl provider (LLM-ready markdown) ✅
1. `providers/firecrawl/` (`config.py` key `FIRECRAWL_API_KEY`, `service.py` —
   `FirecrawlClient` + `FirecrawlAdapter` POST to `https://api.firecrawl.dev/v1/search`
   with `Authorization: Bearer` + `{"query", "limit"}` body, `domain.py` — normalizes `data[]`
   to `SearchResult` (description IS the full LLM-ready markdown).
2. Adds the richest content format the pool lacks (description = full-page markdown with
   headers/tables/bullets, vs plain snippets elsewhere). AIMultiple #2 ranked (Agent Score
   14.58, highest mean relevance 4.30/5). Free tier = 1,000 credits/month (2 credits/10 results
   = ~500 results/month), no card, recurring monthly. Native `/v1/search` endpoint.
3. Map `429`/`402`/`403` → `ProviderQuotaExceeded`; no live balance endpoint
   (credits=None).
4. Append `firecrawl` to the router (7th: tavily, exa, jina, linkup, you, serper, firecrawl).

### Phase 3H — SerpApi provider (Google SERP + answer_box) ✅
1. `providers/serpapi/` (`config.py` key `SERPAPI_API_KEY`, `service.py` —
   `SerpApiClient` + `SerpApiAdapter` GET to `https://serpapi.com/search.json`
   with `api_key` query param + `q`, `engine=google`, `num` params, `domain.py` —
   normalizes `organic_results[]` to `SearchResult` and pulls optional
   `answer_box` into `answer`).
2. Adds a second Google-index source the pool (alongside Serper). Free tier =
   250 searches/month, no card, recurring; optional `answer_box` → Tavily/Serper
   answer parity. Combined Google volume: Serper 2,500 + SerpApi 250 = 2,750/mo.
3. Map `429`/`402`/`403` → `ProviderQuotaExceeded`; no live balance endpoint
   (credits=None; Account API available but burns a search call).
4. Append `serpapi` to the router (8th: tavily, exa, jina, linkup, you, serper,
   firecrawl, serpapi).

### Phase 3I — Geekflare provider (recurring free + grounded answer) ✅
1. `providers/geekflare/` (`config.py` key `GEEKTFLARE_API_KEY`, `service.py` —
   `GeekflareClient` + `GeekflareAdapter` POST to `https://api.geekflare.com/search`
   with `x-api-key` header + `query`/`limit`/`source`/`format` body, `domain.py` —
   normalizes `data[]` of `title`/`url`/`snippet`/`position` to `SearchResult`
   and pulls the LLM-synthesized `answer` + `sources` when `groundedAnswer: true`).
2. Adds a recurring free balance with an **answer** (the `include_answer` gap
   filler for providers with none). Free tier = 500 credits/mo, no card,
   recurring; standard search = 2 credits, grounded answer = 5 credits
   (≈250 plain searches/mo).
3. Honor `req.include_answer` → pass `groundedAnswer: true` (costs 5 credits
   vs 2). Map HTTP `429`/`402`/`403` and API-level `4xx` `apiStatus` →
   `ProviderQuotaExceeded`; no live balance endpoint (credits=None).
4. Append `geekflare` to the router (9th: tavily, exa, jina, linkup, you,
   serper, firecrawl, serpapi, geekflare).

### Phase 3J — TinyFish provider (free unmetered index) ✅
1. `providers/tinyfish/` (`config.py` key `TINYFISH_API_KEY`, `service.py` —
   `TinyFishClient` + `TinyFishAdapter` GET to the **root path**
   `https://api.search.tinyfish.ai/?query=...` with `X-API-Key` header + `query`/
   `results` params, `domain.py` — normalizes `results[]` of `title`/`url`/
   `snippet`/`position`/`site_name` to `SearchResult`).
   NOTE: docs say `GET /search`, but that path returns the web-app HTML (404);
   the real API lives on the root path (same pattern as Jina's `s.jina.ai`).
2. Adds a **truly free, unmetered** independent index — search never draws from
   the wallet (works at $0 balance), no card, ~30 req/min rate limit, ~0.5s
   latency. Great as a free no-cost failover layer at the end of the chain.
3. No answer payload (pure index). Honor `req.include_answer` by forwarding
   intent via the optional `purpose` param (the docs recommend it to improve
   ranking). Map `429`/`402`/`403` → `ProviderQuotaExceeded`; search is unmetered
   so there is no credit balance to report (credits=None).
4. Append `tinyfish` to the router (10th: tavily, exa, jina, linkup, you,
   serper, firecrawl, serpapi, geekflare, tinyfish).

### Phase 4 — Quota observability
1. `usage` tool already queries `/usage` (rate-limited 10/10min) — add caching so
   hot loops don't burn the usage endpoint's own rate limit.
2. Track credit burn per call (`include_usage=True`) and surface cumulative spend
   via a resource (`search://usage`) — feeds the router's budgeting so it can
   prefer the provider with most remaining credits.

### Phase 5 — SOTA routing algorithm (FGTS-VA lineage) — design in `docs/ROUTING.md`, `docs/QUOTA.md`
Router order is now **quality-first, recurring-before-one-time** (see
`router.py` + both docs). Closing the SOTA gaps from the deep research:
1. **Circuit breaker** — CLOSED/OPEN/HALF-OPEN per provider (trip ~5 failures,
   ~60s cooldown, 1 probe) — replaces cooldown-only. THE fail-fast core.
2. **Sliding-window / discounted reward forgetting** — SW-TS or discounted TS so
   an abrupt breakpoint (quota hit/outage) demotes an arm fast (non-stationary).
3. **BwK budget pre-filter** — exclude arms with `remaining <= 0` from
   `available()` before bandit scoring (track per-provider budget from
   `docs/QUOTA.md`, live balance where available).
4. **Answer-aware path** — `include_answer=True` → Linkup → You → Tavily →
   Geekflare (= answer-capable + recurring).
5. **Intent/freshness** — freshness-sensitive queries prefer live-web
   (Linkup/You/Tavily/Geekflare), NOT Exa (weak freshness).

### Phase 6 — Hardening
- Request timeouts per provider (already in configs), semaphore-bounded concurrency,
  per-result `ok`/`error` tagging, dedupe across providers, `Retry-After` honoring.

---

## 10. Sources / rationale

- **The New Stack — 15 Best Practices (2026):** "Treat each MCP server as a bounded
  context." (justifies `domains/<capability>/`)
- **Pragmatic Engineer 2026 surveys:** code-ownership erosion is the #1 senior-engineer
  concern; review = the control step; specs/design (not keystrokes) is the senior role.
- **Cosmic Python** (already in Nexus): Functional Core / Imperative Shell — the
  `domain.py` vs `service.py` split rulebook.
- **FastMCP 3.0 docs:** `tools/resources/prompts` subfolders = "project structure is
  your component registry" (the SOTA organization this repo mirrors).
- **OmniRoute / Argus (2026):** priority routing + fail-fast + cooldown + (later) RRF
  — the router design this repo implements.
- **FGTS-VA — Variance-Aware Feel-Good Thompson Sampling** (Li & Gu, NeurIPS 2025,
  arXiv:2511.02123) — the contextual bandit the quality-router builds on.
- **Bandits with Knapsacks (Badanidiyuru et al.)** — quota-as-constraint pre-filter.
- **Garivier & Moulines (2011)** — sliding-window/discounted UCB/TS for non-stationary arms.
- **AIMultiple search-API benchmark + SimpleQA/FreshQA (Aug 2026)** — provider quality
  and freshness evidence used to order the roster (see `docs/QUOTA.md`, `docs/ROUTING.md`).
