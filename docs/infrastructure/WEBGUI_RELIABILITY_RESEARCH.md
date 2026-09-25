# Web GUI reliability — layered-redundancy research (RESEARCH ONLY)

**Status:** ACTIVE

**2026-07-17. Status: RESEARCH / DESIGN MAP — NOTHING BUILT.** Owner question:
how do we make the web GUI "super reliable" with multiple levels of
redundancy, given what we have? Researched online + mapped onto the actual
GUI (`web/` per `THIN_CLIENT_SWAP.md` §Web GUI: vendored React 18 at `/app`,
served as static files by the single `sfu_library_mcp_http.py` process;
`api.js` live→mock fallback + demo banner; `/health` pill; 12 s timeout;
Playwright e2e sweep exists).

## 0. What we already have (credit where due)

- **Honesty-first fallback (the LAST layer):** every API method falls back to
  `mock.js` on error/timeout, and `ui.js` shows a demo-data banner whenever
  fallback data is on screen. Most GUIs don't have this.
- **Natural bulkheads:** the suite shell iframes one app at a time — a crash
  in analytics cannot take down search (the microfrontend isolation pattern,
  for free).
- **Health awareness:** the AI-status pill probes `/health`.
- **A verification harness:** `scripts/e2e_sweep.mjs` (Playwright) already
  drives every screen at 4 viewports capturing console errors.
- **NEW server-side signals the GUI does not consume yet (deployprep waves
  3–4):** `/health` up≠warm≠degraded (WI-6/9), `degraded: [legs]` and
  `degraded_shards: [...]` response flags (WI-9/10), clean `429 +
  Retry-After` shedding (WI-11), watchdog auto-restart (WI-3).

## 1. The layered model (defense in depth — each layer catches what the one above missed)

| Layer | Principle | Have today | Gap |
|---|---|---|---|
| L1 GUI loads at all | app shell must render with backend DEAD | ❌ static `/app` is served by the SAME process as the API — backend down ⇒ GUI down | service-worker precache of the app shell (cache-first for `web/` + vendor; offline-capable after first visit — the PWA app-shell pattern); portable/Tauri build solves this structurally later |
| L2 transport | absorb transient failures | 12 s timeout only | retries with exponential backoff + **jitter** for search GETs/POSTs, a retry budget (e.g. 2 retries max), honor `Retry-After` on 429 (WI-11 emits it!), in-flight dedupe of identical queries |
| L3 backend chain | more than one place to get an answer | live → mock (2 rungs) | insert the **OpenAlex live API rung**: local API down/degraded ⇒ query OpenAlex directly from the browser (the Live-only tier, in-GUI) ⇒ THEN mock. Client-side circuit breaker per rung (open after N fails, half-open re-probe — the pill's probe loop is already half of this) |
| L4 degraded-state UX | partial truth beats a spinner or a lie | binary live/demo banner | consume the WI-9/10 flags: "sparse leg degraded — showing lexical+dense results"; "index warming — first queries slow" (up≠warm); 429 ⇒ "busy — retrying in Ns" countdown. React error boundary inside each app + shell "reload this app" affordance on iframe crash |
| L5 local data | serve repeats without a backend | none | **stale-while-revalidate query cache** (IndexedDB): render cached results instantly with a "cached" tag, refetch in background. Q12 measured ~85% repeat traffic ⇒ this single layer makes most queries backend-optional |
| L6 server side | the process behind the GUI | single event loop, documented to BLOCK on lazy 24 GB sqlite first-load; no supervisor | run the HTTP entry point under the WI-3 watchdog pattern + WI-6 warmup-at-start (kills the first-call block) + WI-11 overload gate on `/api/search`; optionally serve `/app` statics from a second trivial static server so GUI survives API restarts |
| L7 verification | reliability is measured, not assumed | e2e sweep (functional) | fault-injection cells in the sweep: kill backend mid-session (banner within N s?), 429 storm (countdown UX?), degraded flags (correct banner?); add a GUI smoke phase to `reliability_soak.sh` |

## 2. Failure→experience matrix (what the user sees at each depth, once built)

| Failure | Layer that catches | User experience |
|---|---|---|
| transient API hiccup | L2 retry+jitter | nothing (invisible) |
| repeat query, backend restarting | L5 SWR cache | instant results, "cached" tag |
| SPLADE leg / one shard degraded | L4 flags | results + one-line degraded notice |
| local API down entirely | L3 OpenAlex rung | live results, "via OpenAlex" notice |
| overloaded (429) | L2+L4 | honest "busy, retrying in Ns" |
| everything down, offline | L1 SW shell + L5 cache + mock | app loads, cached/demo data, banner |
| one app crashes | iframe bulkhead + L4 boundary | other apps fine; "reload this app" |

## 3. Sources (researched 2026-07-17)

- App-shell precache + runtime caching split (precache tiny shell; SWR for
  static assets/JSON): [PWA reliability best practices](https://dev.to/azure/25-best-practices-for-pwa-reliability-35eo),
  [offline-first caching strategies](https://www.magicbell.com/blog/offline-first-pwas-service-worker-caching-strategies),
  [app-shell pattern](https://medium.com/codetodeploy/pwa-offline-experience-offline-pages-and-app-shell-pattern-95714355c551),
  [offline caching best practices](https://blog.pixelfreestudio.com/best-practices-for-pwa-offline-caching-strategies/)
- Retry storms & jitter, retry budgets, circuit breaker open/half-open,
  fallback-to-stale: [retry pattern in practice](https://layrs.me/course/hld/12-reliability-patterns/retry),
  [timeout/retry/circuit-breaker](https://dev.to/rafaeljcamara/downstream-resiliency-the-timeout-retry-and-circuit-breaker-patterns-2bej),
  [circuit breakers + retries](https://blog.habsi.net/building-resilient-microservices-with-circuit-breakers-and-retry-patterns/)
- The in-repo measured facts this leans on: WI-9/10/11 verdicts
  (`docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md`), Q12 repeat-traffic skew
  (`disk_streaming_research/`), the single-event-loop first-call block
  (`THIN_CLIENT_SWAP.md` §Web GUI).

## 4. If actioned (pre-register per doc 11 discipline first; all *est.* until then)

Suggested order by payoff/effort: **G1** L5 SWR query cache (small, huge at
85% repeat) → **G2** L2 retry/jitter/Retry-After + dedupe (small) → **G3** L4
degraded/warming/429 UX (small, signals already exist) → **G4** L1 service
worker (medium) → **G5** L6 watchdog+warmup+gate on the HTTP entry point
(medium; reuses WI-3/6/11 wholesale) → **G6** L3 OpenAlex rung + client
breaker (medium) → **G7** L7 fault-injection e2e cells (medium). Bars to
pre-register per item: banner/countdown latency, cache-hit render time,
GUI-loads-offline, zero console errors under each injected fault.
