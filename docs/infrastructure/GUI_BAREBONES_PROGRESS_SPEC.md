# GUI spec — search-progress indication + bare-bones default with toggles

**Status:** ACTIVE

**2026-07-17. DESIGN SPEC (owner-requested). Implementation delegated to the
deployprep wave-5 drive session; this doc is the contract.** Grounded in the
research below + this repository's measured latencies (WI-1/6/7/11).

## 1. Search-progress indication (honest, threshold-staged)

The research consensus ([NN/g response-time thresholds + skeleton-vs-spinner
evidence](https://www.nngroup.com/videos/skeleton-screens-vs-progress-bars-vs-spinners/),
[skeletons 101](https://www.nngroup.com/articles/skeleton-screens/),
[response time in UX](https://www.fundament.design/p/response-time-in-ux)):
<1 s needs NO indicator (a flashing one is worse than nothing); 1–10 s wants
a **skeleton in the shape of the final content** (perceived ~2× faster than a
spinner; feedback makes waits feel 11–15% shorter); >10 s wants determinate
progress or an honest explanation. Fake/indeterminate progress bars are an
anti-pattern; determinate only from REAL signals.

Mapped to our measured reality (warm native ≈ tens of ms; this container /
cold 3–10 s; 9p warming = minutes; 429 = Retry-After seconds):

| Elapsed / state | Indicator | Real signal it's driven by |
|---|---|---|
| < 300 ms | nothing | — |
| 300 ms – 10 s | **skeleton result cards** (same card shape as results — zero layout shift, e2e already asserts this for the banner) + subtle elapsed counter | timer |
| > 10 s AND `/health` says warm=false | message swap: "index warming — the first search after a restart takes longer" (+ keep skeletons) | WI-6 up≠warm flag |
| HTTP 429 | **determinate countdown** "busy — retrying in Ns" then auto-retry | WI-11 `Retry-After` header |
| response carries `degraded`/`degraded_shards` | results render + one-line degraded notice | WI-9/10 flags |
| skeleton shimmer | disabled under `prefers-reduced-motion` (base.css discipline) | — |

Explicitly rejected: spinner-only (perceived slower), fake percent bars
(dishonest — no real total signal exists), per-leg streaming chips (server
returns one response today; do NOT change the serving path for this).

## 2. Bare-bones default + toggles (progressive disclosure)

Principle ([progressive disclosure — IxDF](https://ixdf.org/literature/topics/progressive-disclosure),
[Algolia on density + disclosure in search UX](https://www.algolia.com/blog/ux/information-density-and-progressive-disclosure-search-ux),
[UXPin best practices](https://www.uxpin.com/studio/blog/what-is-progressive-disclosure/)):
map the primary task (type query → read results) to the minimum control set;
tier everything else — essential (always visible), common (one interaction
away), advanced (settings).

**Tier 0 — always visible (the whole default screen):** search box, results
list, ONE status line (backend pill + banner/notice area). Nothing else.

**Tier 1 — one interaction away:** filters as a collapsed "Filters"
expander under the search box (year/type/OA — collapsed by default);
per-result detail expansion.

**Tier 2 — Settings → new "Interface" section (toggles, persisted in
localStorage):**
| Toggle | Default |
|---|---|
| Advanced filters row always open | OFF |
| Saved & History nav | ON (shown) — flipped from OFF 2026-07-18, owner decision: search history must always be in reach; toggle still works |
| Databases tab | OFF |
| Analytics app (suite nav) | OFF |
| Index Manager app (suite nav) | OFF |
| Admin/operator panels | OFF |
| Density: comfortable / compact | comfortable |

**Not toggleable (integrity floor):** the demo-data honesty banner, degraded
notices, and the backend pill can NEVER be hidden — reliability signals are
not clutter (ties to `WEBGUI_RELIABILITY_RESEARCH.md` L4).

**Analytics app data rule (2026-10-12):** the "About this index" app shows only figures
the `/analytics` bundle supplies; a panel without data renders an explicit state
("Not wired: <reason>", "Awaiting click data: N of 20 clicks"), never a placeholder
number. In mock mode every panel is a "live backend unavailable" stub and the demo
banner stays. Engagement posting from the search app is invisible to the user and never
affects the banner, degraded notices or backend pill.

**Constraints:** no serving-path/API changes; pixel work stays inside
`web/`; a11y baseline (base.css) preserved; suite shell keeps hidden apps
unmounted (don't load iframes for toggled-off apps — that's also a
reliability win); e2e sweep extended to cover default-bare state, each
toggle, persistence across reload, and skeleton/countdown states with zero
console errors and zero layout shift.

*Sources: [NN/g skeleton versus progress versus spinner](https://www.nngroup.com/videos/skeleton-screens-vs-progress-bars-vs-spinners/) · [NN/g Skeleton Screens 101](https://www.nngroup.com/articles/skeleton-screens/) · [Response time in UX](https://www.fundament.design/p/response-time-in-ux) · [skeleton-vs-spinner evidence](https://www.onething.design/post/skeleton-screens-vs-loading-spinners) · [IxDF progressive disclosure](https://ixdf.org/literature/topics/progressive-disclosure) · [Algolia search-UX density](https://www.algolia.com/blog/ux/information-density-and-progressive-disclosure-search-ux) · [UXPin progressive disclosure](https://www.uxpin.com/studio/blog/what-is-progressive-disclosure/)*
