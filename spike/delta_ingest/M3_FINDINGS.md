# M3 findings: BM25F score drift (T1) on corpus (a)

**Status:** ACTIVE

Measured 2026-09-30, 20:50Z to 22:58Z, on this host (16 cores, 31 GB, WSL2;
base tantivy sections and meta.sqlite on the `/workspaces` 9p mount, SEISMIC
base shards staged on local disk). The bar is the one in
`docs/delta_ingest/03_SPIKE_PLAN.md` M3, unchanged. Numbers below are copied
from the results file, which is authoritative.

- Results: `data/eval_results/delta_ingest_M3_20260930.json`
- Harness: `scripts/experiments/eval_delta_ingest_m3_bm25f_drift.py`. The
  pre-registration header was committed de5ddd3b before any run. Revisions
  1 to 7 are in the header, each written before the step it changes.
- Code under test: `git archive` snapshots `code_dfc06e6e` (base:B) and
  `code_611ee06b` / `code_e0e3a8f4` (later processes). `git diff dfc06e6e
  611ee06b -- src` is empty, and the later commits touch only the harness.
- Fixture: corpus (a) built by the M2 agent (READY.json, fixture commit
  885c29e7). It is one generation g0001 of 50,000 docs from
  `social_sciences__recent`, re-ingested with one appended sentence ("This
  record was updated after publication."). A livedocs bitset masks their 50,000
  base ordinals.

## Verdicts

| Bar | Number | Verdict |
|---|---|---|
| Median rank change 0 (BM25F leg, title-as-query) | median 0 over 331 docs | **PASS (PARTIAL: 350 of 600 titles)** |
| Displaced non-updated base docs <= 5% of top-10 slots (<= 60 of 1,200) | 1 of 1,200 (0.08%) | **PASS** |

## Setup

- **Arms.** Each arm is a separate process.
  - BASE: gate off, `SFU_DELTA_ROOT=""`, frozen base manifest
    `/home/vscode/work/inplace_update/m4/base_manifest.json`.
  - DELTA: `SFU_DELTA_ROOT=<fixture root>` with the manifest env blank, so
    the composed 9-shard manifest serves, and livedocs is loaded from
    `generations.json`.
  - Both arms: stage dirs blank and checked, federation parallel, remote
    abstracts stubbed.
- **Health.** Every measured process passed the pre-registered checks: SPLADE
  encoder returned 43 terms; `ParallelSeismicBackend` had 8 shards (BASE) or
  9 (DELTA); DELTA had generation [1], 50,000 superseded, livedocs on, the
  shard filter attached and the delta sections loaded; the cross-encoder and
  embedding model were loaded. Every Part B query reached the SEISMIC
  traverse. The log scan found 0 hits for every O12/fallback signature in the
  four measured logs.
- **Order.** base:B, delta:B, base:A, delta:A (revision 2). M2's process ran
  concurrently with each of them (coordinator option b).

## Part B: displacement (fused `search_rrf`, 120 topics, top_k=50, 1 pass per arm)

- **Displaced (in the BASE fused top-10, not an updated id, absent from the
  DELTA fused top-10): 1 of 1,200.**
  - The one case is topic "virtual reality augmented reality immersive
    learning environments". Updated doc W4404859906 entered the fused top-10
    at rank 9 and pushed base doc W4400951113 out of rank 10.
  - Both legs' own top-10s were identical for that topic, so the change came
    from deeper leg ranks.
- **Fused top-10 id lists identical:** 118 of 120. **Fused top-50 identical:**
  113 of 120.
- **Updated ids in the fused top-10:** 2 (BASE) and 3 (DELTA). 1 updated doc
  entered a top-10.
- **Attribution by leg.**
  - BM25F-leg top-10 displacement: 0 (top-10 identical in 119 of 120).
  - SPLADE-leg top-10 displacement: 1 (117 of 120 identical).
  - The one BM25F top-10 change is topic 78: updated doc W4363677066 moved
    from fused rank 2 to rank 1.
- **Final (reranked) top-10 (supplementary, no bar).**
  - Changed in 2 of 120 topics. Displaced on the final list: 0.
  - Both changes (topics 65 and 105) had an identical fused top-10. They come
    from a changed fused top-50 or from rerank float noise; the two are not
    separated here.

## Part A: rank drift (BM25F leg only, `_bm25f_leg(title, 100, None)`)

- **Sample.** Common prefix of 350 titles from the READY.json title sample,
  in its order (pre-registered cap 600; see Deviations).
  - 10 of the 350 titles raise `ValueError: Syntax Error` in tantivy's query
    parser in BOTH arms, so they are excluded; 340 are compared.
  - 331 of the 340 are in both top-100s. 2 are absent in BASE only, 0 in
    DELTA only, and 7 in both.
- **Rank change (DELTA minus BASE), n=331.**
  - Median **0**, mean +0.21, p5 0, p25 0, p75 0, p95 +1, min -8, max +15.
  - Worse in 9.97% of docs, the same in 89.73%, better in 0.30%.
- **Rank-1 share:** BASE 0.847, DELTA 0.782.
- **Own-recall@100:** BASE 0.9735, DELTA 0.9794.
- **Raw score, delta copy over the masked base copy.**
  - Both scores come from the same query in the same DELTA process (the
    pre-mask hit list), n=336.
  - Median **0.982**, p5 0.846, p25 0.939, p75 0.996, p95 1.005, min 0.692,
    max 1.029. The ratio is above 1 in only 11.3% of docs.
  - The pre-mask base-copy score equals the BASE process's score exactly
    (maximum absolute difference 0.0).
- **Mask leak: 0.**
  - No masked base copy survived the mask, either for the queried doc or for
    any updated id in any Part A list.
  - The delta copy and the masked base copy never appeared in the same list
    (0 cases), and filter alignment never failed.
  - Every served copy of the queried doc came from generation 1 (340 of 340).

**What this says about T1.** T1 (`02_DESIGN.md` §3) predicted that a small
section's rare-term IDF would push delta docs *above* base docs. On this
fixture the opposite happens: the delta copy scores about 2% *lower* at the
median, and when its rank moves it gets worse (10% of docs, mostly by one
place).

A likely mechanism, *inferred, not measured*: BM25 IDF is bounded by about
ln(N). The delta section has N = 50,000, while the base section has
N = 23.4M. A title term is at least as frequent in the delta section, because
the doc itself is in it, so its IDF there cannot exceed about ln(50,000),
which is below what the same rare term earns in the 23.4M-doc base section.
The appended sentence also lengthens the abstract field, which lowers its
BM25 contribution. The two effects are not separated here.

The effect is too small to move the median rank or the fused top-10.
Updated docs lose a little, and nothing in the base is pushed out by them.

## Deviations from the pre-registration (all in the harness header)

1. **Part A PARTIAL at 350 of 600.**
   - The index slot, the O12 failures and the host's swap event (below) cost
     about 2.5 h.
   - base:A stopped at row 350 after the coordinator's GO (revision 7).
   - delta:A was stopped at row 350, equal to the BASE rows, at 22:58Z to
     free memory before S0-2 restarted. Rows beyond 350 would not have
     entered the common prefix.
2. **Query errors (revision 6).** The first base:A process crashed at row 57
   on a tantivy parser error. A title whose leg call raises is now an error
   row, identical in both arms and excluded. base:A was re-run from row 0,
   and the crashed rows are discarded (kept on disk).
3. **Interpreter and model copies (revisions 3 and 4, O12).**
   - base:B ran on the repo `.venv` with repo models.
   - delta:B, base:A and delta:A ran on the local venv mirror
     `/home/vscode/work/venv_local` (same packages). SPLADE and the
     cross-encoder were loaded from local copies whose sha256 matches the
     repo files (recorded).
   - The SPLADE tokenizer resolved to `models/sfu-academic-embed-v1` for
     base:B, delta:B and base:A, and to a byte-identical local copy for
     delta:A (sha256 recorded).
4. **Arm order and concurrency.**
   - Part B ran before Part A (revision 2).
   - Two index-loading processes ran at once (M3 plus M2's delta arm), on
     the coordinator's decision.
   - Cores: base:B on 8-15 (latency lock held by B7); delta:B, base:A and
     delta:A on 0-7 (lock free, never held).
5. **Unit.** 1 pass per arm (the plan's fixed inputs say 2).

## O12 and host conditions (recorded in `o12_events_outside_measured_processes`)

- **19:20Z.** A short python start-up hit `[Errno 12] Cannot allocate memory`
  on the 9p mount. The other session says this coincided with a full 16 GB
  swap partition.
- **20:16Z to 21:25Z.** 5 launches of 17 processes all died at import or
  failed health with ENOMEM on `.venv` or model reads over 9p. None ran a
  query.
- **Root cause, verified by the coordinator with strace:** `read` and
  `getdents64` return ENOMEM on the 9p mount. The kernel 9p client needs
  order-3/4 contiguous pages, and there were almost none free in the Normal
  zone. `/proc/sys` is read-only, so no sysctl fix is possible. The
  workarounds were the local venv mirror, local model copies and page-cache
  pre-warming.
- **~22:25Z.** swapoff/swapon on the host while base:A ran.
- **Timings.** All timings are invalid (`timings_valid: false`): shared host,
  concurrent M2, nice 10, no latency lock.

## Not measured

- The remaining 250 titles of the pre-registered 600.
- A second pass of either part, and a gate-off vs gate-off noise control for
  Part B. M1 on 2026-09-29 found 120/120 identical for gate-off vs an empty
  root, on 1 pass.
- Separating the IDF effect from the appended-sentence length effect.
- Corpus (b) (real new works). Corpus (a) re-ingests existing docs, so it
  tests updates, not additions of new rare-term docs, where T1's original
  worry (new docs outranking base docs) could still apply.
- A title-only or abstract-only score split.

## Issue found, not fixed

`ThinClientRetriever._bm25f_leg` (`source/lib/thinclient/retriever.py`, the
`idx.parse_query(text, ["title"])` line in `_bm25f_leg`) raises
`ValueError: Syntax Error` on queries containing upper-case `IN` and similar
operator words. The sanitiser removes only non-alphanumerics. This hit 10 of
350 real titles (2.9%) in this sample, all upper-case titles. Whether the
serving path catches it is not checked here.

## Input for score normalisation (M3 passed, so no follow-up is opened by this bar)

M3 did not fail, so the plan's "per-section score normalisation" follow-up is
not triggered. If it is opened for corpus (b) anyway, these numbers say:

- The drift measured here runs against delta docs (median ratio 0.982, p5
  0.846) and is small next to the gap between rank 1 and rank 2. A
  normaliser that inflates small-section scores would push updated docs
  above their base rank, the opposite of what is needed here.
- The realistic risk is new docs whose rare terms carry different IDFs. That
  needs a corpus (b) measurement of the same Part A/B statistics before any
  design.
