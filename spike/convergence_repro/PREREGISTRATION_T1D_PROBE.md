# Pre-registration DRAFT — Tier-1d access-histogram probe (LOCAL variant)

**Date:** 2026-09-06 · **Status: DRAFT — method not frozen; no probe run may
be recorded against this doc yet.** This doc, when frozen, closes
`PREREGISTRATION_TIER1D.md` §6 **gap 3** and un-severs **S-realprofile
(§3.6)** via its own amendment. It AMENDS gap 3's original assumption that
the probe must run "on the OCI box": the histogram is a **counting**
measurement (which postings/pages are touched, how often), not a timing one,
so it does not need the serve box's latency fidelity — a local run costs no
OCI billing and N7 does not bind it. The SML 16 GB replicate battery is NOT
this probe (that is real-stack timing work and stays behind the OCI/native
decision, in the sml pre-reg).

## 1. What is measured

The per-posting (primary) or per-page (fallback) access frequency of the
served 150M SEISMIC index under a pinned query mix. Outputs, in order of use:

1. **Skew bracket:** the measured mass-vs-fraction curve (what fraction of
   postings/pages carries 0.50/0.80/0.95 of accesses), reported against the
   synthetic `hotset:h:m` grid — this replaces the guessed 20/80 with the
   real index's coordinates and tells us where the T1d-2 sweep brackets it.
2. **S-realprofile inputs:** the exported ranking (page id → access rank) and
   an initial-residency profile, in a form `t1d_cell.py` can consume (a
   follow-up driver flag, its own gap — see §5).
3. **Clustering statistic** (for the T1d-12 arm): run-length distribution of
   hot pages in file order at the measured h — does the real hot set look
   like `hotsetc`'s extents, and with what E?

## 2. Method A (primary): posting-level counters in the instrumented fork

Instrument `spike/seismic_testbed_instrumented/` to count block/posting
accesses during query replay; replay the pinned query mix N times against
the local 150M index (read-only), dump counters, map posting → byte range →
page id via the manifest. Environment-independent: counts are a property of
the index + queries, not of the host, WSL2, or 9p.

## 3. Method B (fallback): page-level residency sampling

Cold-start the local serving stack, replay the mix, sample `mincore` deltas
over the mapped shards between queries. Cheaper to build, but confounded by
readahead (a touched page and a read-ahead page are indistinguishable) and
by 9p caching in this container — usable only as a coarse cross-check on
Method A, never as the S-realprofile input on its own.

## 4. To freeze (each its own commit)

1. **Query mix pinned:** the exact query list (the 40-query real workload +
   the demo mix), replay order seed, and N (draft intent: N=25 replays,
   ≥1,000 query executions total).
2. **Counter instrumentation landed** in the instrumented fork, with an
   uncapped smoke run showing counts are deterministic across two identical
   replays (tolerance: exact equality — counting, not sampling).
3. **Output schema pinned:** histogram JSON + ranking export path under
   `data/eval_results/t1dprobe_*.json`, cited by path from the S-realprofile
   amendment.

## 5. Non-interference & downstream gaps

- Read-only throughout: the replay queries the serving path; nothing writes
  under `data/seismic_150m/` (IRREPLACEABLE, READ-ONLY — absolute).
- Runs in the dev container; no host windows, no `.wslconfig` dependency,
  no OCI cost.
- Downstream gap (not this doc): a `t1d_cell.py` mode that seeds residency
  AND draws touches from an imported ranking/profile file — required before
  S-realprofile can run; freeze it with the S-realprofile amendment to
  `PREREGISTRATION_TIER1D.md`.

## 6. Efficacy (per CLAUDE.md)

The probe's deliverable is measured numbers in this doc (mass-vs-fraction
table, clustering statistic, absolute dates) + the committed histogram
JSONs. No serving-path claims are made; nothing here changes any Tier-1d
verdict.

## 7. FROZEN 2026-09-12 — method, query mix, schema (local variant, Method A)

**Status: FROZEN 2026-09-12** (this section; §1–§6 above stand as the
design). Frozen before any full-index run was recorded: the script landed at
`b1031bfc` and its one-shard, 12-draw smoke run (scratchpad only, not a
result file) established only that the outputs populate. The full run
started after this section was written.

**Prior measurement acknowledged (correction to §4 item 2 and to
`PREREGISTRATION_TIER1D.md` §6 gap 3).** The counter the draft says must
"land in the instrumented fork" already exists in the served binding:
`MmapSeismicIndex.search_visited` (the Q6/E5 instrument), and the same
histogram was measured twice in July — **Q12 (2026-07-13)** on the E5 dv-v1
manifest and **Q12b (2026-07-14)** on the served E8 dv-v2 manifest
(`data/eval_results/q12b_access_skew_production_20260714.json`: hot-set-80
3.07 GB = 748,319 of 7,528,445 forward pages = 9.9%, Gini 0.550, 400
production-shaped draws, 350.8 s). Q12b kept three curve points and no
ranking; this probe re-runs Q12b's method keeping everything the T1d line
needs. Gap 3's "must run on the OCI box" wording is superseded by this
doc's header: counting, not timing.

1. **Query mix (pinned):** Q12b's production-shaped builder, verbatim
   semantics — Zipf(s=1.0) over the 49 subjects of
   `data/sfu_eval_queries.json` (subjects ordered by catalog size desc),
   uniform pick with replacement inside the drawn subject. **N = 1,000
   draws, seed 20260912**, replay order = draw order, one replay per run
   (an identical replay multiplies every count by the replay factor and
   moves nothing; the ≥1,000-execution intent of §4 item 1 is met by the
   draw count). The drawn log is written verbatim to
   `data/eval_results/t1dprobe_querylog_20260912.json` with its sha256.
2. **Instrument:** `search_visited` at the served shape (top_k=50 → k'=100,
   heap_factor 0.8, query_cut all-terms), E8 dv-v2 manifest
   `seismic_c25_shards_150m_mmap_e5_v2.json`; page = word_offset·8 ÷ 4096;
   within-query dedup, cross-query accumulation; forward pages only.
   **Determinism bar: two independent full runs (`run1`, `run2`) must
   produce byte-identical per-shard count arrays** — compared by the
   sha256 recorded as `counts_sha256` in each result JSON. Exact equality;
   any difference fails the probe (counting, not sampling).
3. **Output schema (pinned):** `scripts/seismic_testbed/t1dprobe_access_histogram.py`
   → `data/eval_results/t1dprobe_hist_20260912_{run1,run2}.json` (summary
   fields Q12b-compatible; pooled and per-shard mass-vs-fraction curves on
   a fixed 0.0001–1 grid against BOTH denominators, all forward pages and
   touched pages; `at_mass` at 0.50/0.80/0.90/0.95/0.99; mass at the
   synthetic grid h ∈ {0.05, 0.10, 0.20}; touches-per-page histogram;
   hot-80 clustering: extents, run-length p50/p90/p99/max, share of hot
   pages in runs ≥ {1,2,4,8,16,64,256}, gap p50, and the
   uniform-random expected extent count as the null) and
   `data/eval_results/t1dprobe_ranking_20260912_run1.npz` (per shard:
   pages sorted by count desc with ties by page id, and their counts —
   the S-realprofile access-ranking input).

**Readouts recorded on completion (below this line, dated).** No serving
claims; no Tier-1d verdict moves. The remaining S-realprofile gap after
this probe is the driver side (§5: a `t1d_cell.py` mode that seeds
residency and draws touches from an imported ranking) and an
initial-residency profile of the real stack, which this counting probe
does not measure.

## 8. RESULTS 2026-09-12 — recorded against §7 (dev container, WSL2 9p, counting only)

**Determinism bar: PASS.** `run1` (410.0 s) and `run2` (347.0 s), each 1,000
draws from seed 20260912 (query-log sha256 `3521432158b0…`), produced
byte-identical per-shard count arrays — `counts_sha256`
`fa311872fa569c4eceb0a6b4fd74f0f34168e55d02b9b7410452e8bec96f0603` in both
result files. 1,000/1,000 queries executed, 0 empty encodes.

**Chart:** https://claude.ai/code/artifact/e0be4531-9061-43bc-8c5b-95cfe1d62eaa
(Lorenz curve against the synthetic `hotset:h:m` grid, per-shard overlay,
run-length and touches-per-page histograms, the tables below, provenance).

### 8.1 Skew bracket (readout 1) — pooled over 8 shards, forward pages only

Forward index 7,528,441 pages = 30.84 GB; 2,017,232 distinct pages touched
(26.8%); 42,119,685 page-touches; pages/query p50 40,112; Gini over touched
pages 0.568; 99.8% of touches land on a page some other query also touched.

| share of touches | pages | GB | of forward | of touched |
|---|---|---|---|---|
| 50% | 269,308 | 1.10 | **3.58%** | 13.4% |
| 80% | 783,878 | 3.21 | **10.41%** | 38.9% |
| 90% | 1,142,558 | 4.68 | 15.18% | 56.6% |
| 95% | 1,423,830 | 5.83 | 18.91% | 70.6% |
| 99% | 1,793,755 | 7.35 | 23.83% | 88.9% |

Against the synthetic grid (mass carried by the hottest h of *forward*
pages): h=0.05 → **0.589**, h=0.10 → **0.789**, h=0.20 → **0.961**. So the
real index sits at **`hotset:0.10:0.80`** on the forward-page denominator —
the T1d-11 sweep rung, not the judged `0.20:0.80` cell (which on this
denominator corresponds to 96% mass, i.e. a much *sharper* hot set than the
judged cells drew). On the touched-page denominator the hot set is
`hotset:0.39:0.80` (h=0.20 of touched pages carries only 0.609). Which
denominator maps onto the synthetic's R is a design decision for the
S-realprofile amendment — the synthetic's R has no never-touched tail,
so the touched-page form is the closer analogue of R while the forward-page
form is the closer analogue of the mapped file; record both.

Consistency with Q12b (2026-07-14, 400 draws, seed 20260714): hot-80 3.07 GB
→ 3.21 GB, Gini 0.550 → 0.568 — the same curve at 2.5× the draws.

### 8.2 Clustering statistic (readout 3) — per-shard hot-80 sets, file order

783,882 hot pages fall into **446,508 extents**: run length mean 1.76, p50
**1**, p90 3, p99 10, max 266. 39.2% of hot pages are singletons; 13.8% sit
in runs ≥8; 1.7% in runs ≥64; 0.17% in runs ≥256. Random placement of the
same page count would give ~702,262 extents, so the real hot set is only
**1.57× more clustered than random** — nothing like the T1d-12 `hotsetc`
arm's E=8 contiguous extents. Per shard the picture is uniform (extents
53,769–57,901; p50/p90 1/3 on every shard; max 208–266; Gini 0.559–0.575).
Readout: at hot-80 granularity, readahead cannot buy much on this layout —
consistent with §31's layout-blind finding, and it bounds what a `hotsetc`
cell can claim to model.

### 8.3 S-realprofile inputs (readout 2)

`data/eval_results/t1dprobe_ranking_20260912_run1.npz` — per shard
`shard{i}_pages` (uint32, count-desc, ties by page id) and
`shard{i}_counts` (uint32), plus `forward_total_pages`. This is the access
ranking; the initial-residency profile (§5) is NOT measured here and the
driver import mode (§5) is still unbuilt, so S-realprofile remains severed
on those two items only. Gap 3 of `PREREGISTRATION_TIER1D.md` §6 is
CLOSED by this section.

Result files (committed `14ceea4d`): `t1dprobe_hist_20260912_{run1,run2}.json`,
`t1dprobe_ranking_20260912_run1.npz`, `t1dprobe_querylog_20260912.json`,
runlogs `_t1dprobe_run{1,2}_20260912.log`. Script at `b1031bfc`.
