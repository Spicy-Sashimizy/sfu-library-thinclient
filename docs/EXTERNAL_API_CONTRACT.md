# External-API client contract (OpenAlex, Semantic Scholar, arXiv, CrossRef)

**Status:** ACTIVE

Consolidated 2026-09-01 from code comments (the rules were previously stated
only in `source/lib/openalex.py`, `semantic_scholar.py`, `retry.py`,
`arxiv_fetcher.py`). The code is authoritative.

## Circuit breaker & retry (lib/retry.py)

- **One breaker failure per LOGICAL request** — recorded only on the final
  exhausted attempt. Recording per-attempt over-counts (max_retries=3 ⇒ 4
  failures) and trips a threshold-5 breaker after a single failing
  request. This rule applies in every client and is pinned on the live
  clients by `source/tests/test_openalex_client.py::TestOpenAlexCircuitBreakerWithRetries`
  and `source/tests/test_semantic_scholar_client.py::TestS2CircuitBreakerWithRetries`
  (repointed 2026-10-11: the unused `retry_with_backoff` decorator and its
  `test_retry.py` cases were removed; lib/retry.py now holds only the
  `CircuitBreaker`).
- HALF_OPEN allows exactly ONE test request through.
- **4xx (except 429) is not a service outage**: 404 is normal for
  missing-DOI/ID lookups, 400 is a malformed filter — treat as not-found,
  no retry, no breaker count.
- The federated router must never crash the calling handler; clients
  narrow their own exceptions, the router's broad except is deliberate.
- Failures in fire-and-forget paths (usage tracking, notify) never
  degrade the live search path.

## Rate limits & budgets

> **Note 2026-09-29 (web-sourced, unverified against the live client):**
> OpenAlex announced on 2026-01-13 that API keys are mandatory from
> 2026-02-13 and that the `mailto` polite pool is gone ("No more polite
> pool!"); pricing is per-call (`meta.cost_usd` in every response, free key
> ≈ $1/day) and the since-date filters (`from_updated_date`,
> `from_created_date`) are paid-plan only. The rows below still describe
> what `lib/openalex.py` DOES today (polite-pool fallback, 900/day tracker),
> which is the code's behaviour, not OpenAlex's current terms. Sources and
> detail: `docs/delta_ingest/01_RESEARCH.md` §1.2. Re-verifying the client
> is open work, outside the delta-ingest spike.
>
> **Verified 2026-10-29 against the live endpoint with the project key**
> (`/works?search=machine learning`, direct `requests` probe, 1 call each):
> `from_publication_date`, `to_publication_date` and `publication_year`
> filters all return 200 on the free key (785,833 works from 2026-01-01;
> 272,910 in 2026-07-01..2026-10-29), each answer carrying
> `meta.cost_usd = 0.001`; the same request with NO key also returned 200,
> so anonymous access was still served that day. `from_updated_date` →
> **429 `Plan upgrade required`** ("part of daily sync, which comes with the
> Member+ and Partner plans"). A malformed or bogus key → **401 `Invalid or
> missing API key`**, which `_get` swallows as not-found; since 2026-10-29
> `search_works` marks that answer `degraded: True` and the federated
> router falls back to the local route with a note. Operational trap: an
> `.env` with CRLF line endings sourced in a shell appends `\r` to the key
> and produces exactly that 401. The serving search leg sends only
> publication-date filters, never the sync filters.
>
> **OpenAlex support answer, received 2026-10-29** (ticket by the owner;
> answered by an agent under staff supervision — authoritative for the free
> plan's terms, quoted figures): no academic or ad-hoc increases on free
> keys; the incremental options (daily premium snapshot, changefiles,
> `from_updated_date` / `from_created_date`) are Member+ and Partner only.
> The free key is **$1 a day = 10,000 credits**: a **search costs 10
> credits**, a **filter page costs 1 credit** (up to **200 works** per page),
> and a **single-work GET by id (`/works/W…`) costs nothing** and returns the
> abstract. Suggested free feed for new publications: `from_publication_date`
> + `sort=publication_date` (measured in `docs/delta_ingest/01_RESEARCH.md`
> §1.2a). **Consequences for this client (open work, nothing changed):**
> `DailyCallTracker` counts every 2xx as one call against 900, which is the
> right ceiling for searches (10,000 / 10 = 1,000) but charges the
> serving-path abstract hydration (`fetch_abstracts_by_ids`, a filter-only
> page of 50 ids = 1 credit) ten times its real price; a credit-aware tracker
> reading `meta.cost_usd` (1 credit = $0.0001 as observed) would be exact. A
> live-routed search with a date filter costs 11 credits, so the 900-search
> ceiling stands for the federated router.

| Service | Limit | Notes |
|---|---|---|
| OpenAlex | api_key: 100 req/s · polite pool (mailto): 10 req/s · neither: 1 req/s | daily budget default 900 (free plan ~1,000/day, 10% headroom); tracker file lives under `/tmp` — cleared on container restart (first-run/daily-reset messages are normal, not errors) |
| Semantic Scholar | free tier 100 req / 5 min | longer base delay on 429 |
| arXiv | 100 results/request cap | polite-use delay between requests |
| CrossRef | — | blocking enrichment runs off the event loop so DOIs enrich concurrently |

- Polite-pool mailto and the `User-Agent` contact both come from `OPENALEX_MAILTO` (no built-in address since 2026-10-10; unset ⇒ no contact sent, `docs/ENV_GATES.md`). Strip `api_key` from
  any error string so it never lands in logs — `lib.openalex.redact_api_key`
  does this for every `_get` log line and for the retriever's direct
  fallback (pinned by `test_error_logs_redact_api_key`,
  `test_direct_fallback_error_log_redacts_key`).
- Only **successful** (2xx) OpenAlex responses increment the daily tracker;
  cache hits, 429s, 4xx-as-not-found and requests blocked by the budget or
  the breaker cost nothing against it. At the limit `_get` returns `None`
  (never raises); `search_works` turns that into a `degraded: True` answer
  (2026-10-29) and every other caller treats it as "no data".
- Batch abstract fetches from serving-path code 429-storm the polite pool
  — harnesses set `remote_abstracts=False` (see
  `CODE_INVARIANTS_SCRIPTS.md` WI-9 entry).

## Thin-client abstract hydration goes through `OpenAlexClient` (2026-09-25)

- The serving retriever (`ThinClientRetriever`, built in
  `lib.tools._get_federated_router`) is constructed with
  `remote_abstract_fetcher=_get_openalex().fetch_abstracts_by_ids` and
  `openalex_api_key=cfg.openalex_api_key`. Remote abstracts for ids missing
  from the local sidecar therefore go through the SHARED client: `api_key`
  query parameter (else `mailto`), daily tracker, circuit breaker, 5-minute
  response cache. Before 2026-09-25 the retriever called
  `api.openalex.org/works` directly with `mailto` only, outside all of these.
- Request shape: `GET /works?filter=openalex_id:W1|W2|…&per-page=<n>&select=id,abstract_inverted_index`,
  ≤ 50 ids per request, abstracts rebuilt by `lib.openalex.reconstruct_abstract`.
- **Serving-path overrides**: `fetch_abstracts_by_ids` calls `_get` with
  `max_retries=0`, `timeout=15` — a 429 or timeout is one failed request,
  never a 2 s/8 s/32 s backoff sleep inside a live query. The failure still
  counts once on the breaker, so a 429 storm opens the breaker after 5
  failed fetches and further fetches skip the network for its timeout
  (120 s client default). **The breaker and the daily budget are shared
  with the router's live OpenAlex search leg and the tools**: abstract
  429s can open the breaker for them too, and abstract fetches draw on the
  same 900/day limit.
- **Budget per served query**: the LOCAL_RRF path hydrates two legs
  (BM25F, SPLADE) inside one `hydrate_scope`, each ≤ `top_k` ids and only
  ids not already asked in the request, so with `top_k ≤ 50` a served
  cache miss costs **≤ 2 tracker calls** (1 per leg; ≤ 1 when the legs'
  missing ids are all shared or all hot-section-local; 0 when the id set is
  in the 5-minute cache). Worst case against the 900/day default ≈ 450
  cache-miss queries per day with every candidate cold, after which ALL
  OpenAlex client calls (search leg, tools, abstracts) are blocked until
  local midnight. *est.* — the per-query distribution is unmeasured.
- A blocked, rate-limited or failed abstract fetch degrades to "no
  abstract" for those ids; it never raises into the search (the retriever
  also catches any exception from the injected fetcher). Offline harnesses
  that construct the retriever without a fetcher keep the unbudgeted direct
  path (it sends `api_key` only if one is passed) — prefer
  `remote_abstracts=False` there (WI-9).

## Live-API ↔ local-index write policy

- **CLOSED 2026-10-11:** the OpenAlex→OpenSearch push (`OpenAlexClient._push_to_opensearch`,
  the `opensearch_*` constructor parameters, `_coerce_year`, the `local_opensearch_enabled`
  feature gate and `source/tests/test_openalex_push.py`) was removed; the ingest path is
  `spike/delta_ingest/` (`docs/delta_ingest/`). The live OpenAlex client no longer writes
  to any local index.
