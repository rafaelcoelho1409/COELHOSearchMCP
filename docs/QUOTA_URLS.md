# Provider Quota URLs — Check Current Usage per API Key (Aug 2026)

> Best URL per provider to check quota/credits remaining for the **API key in use**.
> Verified via live web search 2026-08-29 (providers: tavily, serper, linkup, you, firecrawl, exa, geekflare, tinyfish, jina).

| # | Provider | Dashboard (UI) — best URL | Programmatic API (if any) | What you see |
|---|---|---|---|---|
| 1 | **linkup** | **https://app.linkup.so/** → Billing section | — | Current consumption; docs confirm *"view your current consumption in the Billing section of the Linkup app"* — [docs.linkup.so/pages/documentation/platform/pricing](https://docs.linkup.so/pages/documentation/platform/pricing) |
| 2 | **you.com** | **https://you.com/platform** → Billing | `GET https://api.you.com/v1/billing/account_balance` `H: X-API-Key: $YDC_API_KEY` | Remaining credits + usage history; analytics at [you.com/platform/analytics](https://you.com/platform/analytics); docs at [you.com/docs/administration/billing](https://you.com/docs/administration/billing) |
| 3 | **exa** | **https://dashboard.exa.ai/** | `GET /get-api-key-usage` — [exa.ai/docs/reference/team-management/get-api-key-usage](https://exa.ai/docs/reference/team-management/get-api-key-usage) | Credit balance, billing, per-key usage analytics; billing overview at [exa.ai/docs/reference/billing](https://exa.ai/docs/reference/billing); pricing at [exa.ai/pricing](https://exa.ai/pricing) |
| 4 | **geekflare** | **https://dash.geekflare.com** → Account Summary → Current Cycle Usage / Billing | — | Monthly credits, RPS, top-up packs, days log retention |
| 5 | **tavily** | **https://app.tavily.com/** (also [tavily.com](https://tavily.com/)) → Dashboard → API Keys | — | Account-level quota (shared across keys), remaining searches/mo; pricing at [tavily.com/pricing](https://www.tavily.com/pricing) |
| 6 | **tinyfish** | **https://agent.tinyfish.ai/** (sign-up) + [tinyfish.ai/pricing](https://www.tinyfish.ai/pricing) → account dashboard | — | **Search & Fetch are unmetered/free** (30 RPM search, 150 RPM fetch, no Wallet draw even at $0). Wallet balance & credit rates live in dashboard — [tinyfish.ai/pricing](https://www.tinyfish.ai/pricing) → *"Your credit rates and balance live in your account dashboard"* |
| 7 | **firecrawl** | **https://www.firecrawl.dev/app** (also [firecrawl.dev/app/settings?tab=billing](https://www.firecrawl.dev/app/settings?tab=billing)) | `GET /credit-usage` and `/credit-usage-historical` — [docs.firecrawl.dev/api-reference/endpoint/credit-usage](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage) | Current + historical credit usage; docs at [docs.firecrawl.dev/billing](https://docs.firecrawl.dev/billing) and [docs.firecrawl.dev/dashboard](https://docs.firecrawl.dev/dashboard) |
| 8 | **serper** | **https://serper.dev/api-keys** | — | Named API keys, remaining prepaid credits (6-mo expiry), QPS; note: *no rate-limit headers* on wire |
| 9 | **jina** | **https://jina.ai/reader** → **API Key & Billing** tab (or **Manage API Key** when logged in) | — | Recent usage history + remaining tokens (10M free tokens shared across Reader/Embeddings/Reranker) |
| 10 | **serpapi** | **https://serpapi.com/dashboard** | `GET https://serpapi.com/account.json?api_key=SECRET` (or `https://serpapi.com/account?api_key=SECRET`) — [serpapi.com/account-api](https://serpapi.com/account-api) — free, not counted toward quota | Searches this month, plan limit, searches left, renewal date, hourly throughput; response: `plan_searches_left`, `total_searches_left`, `this_month_usage` |

## Quick programmatic checks

```bash
# You.com — balance in cents (divide by 100 → USD)
curl -sS -X GET "https://api.you.com/v1/billing/account_balance" \
  -H "X-API-Key: $YDC_API_KEY" -H "Accept: application/json"

# SerpAPI — free Account API
curl -sS "https://serpapi.com/account.json?api_key=$SERPAPI_API_KEY"

# Firecrawl — credit usage
curl -sS "https://api.firecrawl.dev/v2/credit-usage" \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY"

# Exa — per-key usage (see dashboard.exa.ai for team-management endpoint)
# Requires team-management API call — see https://exa.ai/docs/reference/team-management/get-api-key-usage
```

## Notes

- **TinyFish** search/fetch quota pages never exhaust — monitor Agent/Browser wallet only.
- **Tavily** is the only provider with a live balance surfaced in our `usage` tool today; all others use static ceilings in `docs/QUOTA.md` ±20%. Wire these dashboards/APIs into `search_credits_remaining()` when adding live checks.
- All UI dashboards require login with the same account that owns the API key. For org keys, balance is the shared pool.
- Keep `docs/QUOTA.md` as the BwK capacity source of truth; this file is the **where-to-click** companion.
