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

### Phase 3D — RRF merge (optional, cross-provider quality)
- If/when you want multi-provider merges (not just failover), add Reciprocal Rank
  Fusion in `router.py` to combine results across providers (competitors like
  Argus do this: `failover + RRF ranking`). Only when single-provider failover
  is proven.

### Phase 4 — Quota observability
1. `usage` tool already queries `/usage` (rate-limited 10/10min) — add caching so
   hot loops don't burn the usage endpoint's own rate limit.
2. Track credit burn per call (`include_usage=True`) and surface cumulative spend
   via a resource (`search://usage`) — feeds the router's budgeting so it can
   prefer the provider with most remaining credits.

### Phase 5 — Hardening
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
