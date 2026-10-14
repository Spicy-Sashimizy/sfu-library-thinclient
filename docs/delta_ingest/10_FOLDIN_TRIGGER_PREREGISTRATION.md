# 10 — Pre-registration: the fold-in trigger ("cutback") — committing delta generations into rebuilt base shards

**Status:** ACTIVE

**PRE-REGISTERED 2026-10-01, NOTHING RUN; DESIGN ONLY until the gates of §3
pass.** FROZEN 2026-10-01 at the commit that adds this file (parent
`5707adce`; `git log --diff-filter=A --format=%H --
docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md` prints it). Every
bar is numeric and written before any number for it exists; a failed bar is
recorded as FAIL and never re-cut; clarifications go in a dated addendum at
the end, written BEFORE the run they affect, never loosening a bar. Written
by item P of the 2026-10-01 dispatch; documents only (no index loaded, no
measurement). It is the pre-registration that `02_DESIGN.md` §4 item 11
(added 2026-09-30 at the owner's request) says must be written before any
run.

## 0. What the trigger is

Compaction (`02_DESIGN.md` §1.7, `09_M4_FOLLOWUP_PREREGISTRATION.md` L1)
only merges delta generations into bigger delta generations; the delta keeps
growing at the churn rate and every updated doc keeps a masked dead copy in
its base shard. The **fold-in** of base shard *s* builds a new shard *s′* =
(base *s* minus its masked docs) + (live delta docs routed to *s*) by the
twin route (`02_DESIGN.md` §1.7: f16 twin → jsonl → `SeismicIndex.build`
with the G2 params → `c1a_mmap_index` → `convert_f16_to_dotvbyte
--value-scale perdoc`), and then serves *s′* in place of *s*, dropping the
folded docs from the delta layer. The **trigger** ("cutback") decides, per
shard, when that happens.

## 1. Parameters and candidate values (frozen)

All per base shard *s*; the fold of *s* is triggered when ANY threshold
fires. Defaults per profile are chosen by §6 F7 from the candidates; until
then nothing ships ON.

| Parameter (env / profile dial) | Definition (how it is measured) | Candidates |
|---|---|---|
| `SFU_DELTA_FOLDIN_FRAC` (a) | live delta docs routed to *s* (ledger, `status='live'`, any generation or the buffer, routed by §3 G2) ÷ base docs of *s* (`n_docs` of *s* in the served shard manifest, e.g. 18,799,322 for shard 0). Computed at every `publish()` by one SQL count | 0.02, 0.05, 0.10, 0.20 |
| `SFU_DELTA_FOLDIN_DEAD_FRAC` (d) | masked base docs of *s* (livedocs bits set for ordinals of docs routed to *s*: deleted + superseded base copies) ÷ base docs of *s*. Added here because dead copies inflate SEISMIC over-fetch, and livedocs was measured only at 0.1% density (`03_SPIKE_PLAN.md` Livedocs row) | 0.05, 0.10, 0.20 |
| `SFU_DELTA_FOLDIN_TAX_MS` (b) | the modelled per-query tax of the live delta layer, `T = a + b·G + c·D` (G live generations, D live delta docs in millions), coefficients from 09's R1 (a, b) and §6 F0 (c); one global value, attributed to *s* in proportion to *s*'s share of D (a generation mixes shards, so per-shard tax is not directly observable). Fires for the shard with the largest share | 8, 16, 32 ms (8 = one M4 generation budget) |
| `SFU_DELTA_FOLDIN_MAX_AGE` (c) | age of the oldest live delta doc routed to *s* (ledger stage time) | 14, 30, 90 days |
| `SFU_DELTA_FOLDIN_MAX_CONCURRENT` (dial) | folds running at once on the host | laptop 0 (see §7) / desktop_gpu 1 / server ⌊RSS cap ÷ (1.25 × measured fold peak)⌋ |

Hysteresis (fixed): after a fold of *s* publishes, no trigger for *s* is
evaluated for 24 h, so a mis-set threshold cannot loop.

## 2. What the candidates mean in calendar time (*est.*, derived from measured churn)

Measured churn (closed in-place spike, `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md`
results row S0-1, `data/eval_results/inplace_s0_20260930.json`, shard 0,
quarter Q1 = 2026-06-17 .. 2026-09-15 = 91 days, part-file sample f = 0.1005):
**27.4% of the shard's docs updated** (5.15 M, CI 24.6–30.4%), **2.83 M new
docs (15.1%)**, **6.0% deleted** (1.13 M); 7,977,460 upserts in total. With
the base-hash text filter (M7-seed: 3.959 touched : text-changed among
in-base docs) the text-changed updates are *est.* 1.30 M, so 4.13 M upserts
would need new vectors (`08_…` §2 table, same arithmetic).

Rates per shard (*est.*): as coded (every content-hash change is a delta
upsert) 87,692 upserts/day = **0.466%/day**; text-filtered (metadata-only
updates kept out of the delta SEISMIC shard — needs O14 + a ledger rule, not
built) 45,394/day = **0.241%/day**; dead-copy growth (updated + deleted)
**0.367%/day** as coded, 0.142%/day text-filtered.

Days from a fresh fold until a threshold fires (*est.*; linear, no fold in
between):

| threshold | (a) as coded | (a) text-filtered | (d) as coded | (d) text-filtered |
|---|---|---|---|---|
| 0.02 | 4.3 | 8.3 | — | — |
| 0.05 | 10.7 | 20.7 | 13.6 | 35.2 |
| 0.10 | 21.4 | 41.4 | 27.2 | 70.4 |
| 0.20 | 42.9 | 82.8 | 54.5 | 140.9 |

So (a) fires first at every candidate; (c) at 14 days only matters for the
text-filtered stream with (a) ≥ 0.05. Across 8 shards a fold fires somewhere
every *est.* 1.3 days at (a) = 0.05 as coded. Caveats that make every number
above *est.*: one shard, one quarter sampled at 10% of part files; Q1 is the
first quarter after the 2026-06-16 build, so it carries accumulated drift
(steady-state churn UNMEASURED, `02_DESIGN.md` §4 item 1); the re-encoded
vectors average 122.5 nnz/doc vs 87.6 in the base (`08_…` §0.3, inferred,
unverified) which may inflate demand.

Fold cost at those cadences (*est.* from M9, shard 0, under host load,
`data/eval_results/delta_ingest_twin_rebuild_20260929.json`): dump 220 s +
build 1,919 s + c1a 365 s + dotvbyte 195 s ≈ **45 min per shard**, peak RSS
8.2 GB, 38.9 GB jsonl scratch. At (a) = 0.05 as coded: 8 folds per
~10.7 days ≈ 34 min of fold per day on `desktop_gpu` (*est.*).

## 3. Prerequisites — explicit gates (no fold-in run before G1–G4 hold)

**G1 — the twin route's fidelity.** M9 FAILED its parity bar (overlap@10
rebuilt-vs-served 0.9858 / 0.9870 vs 0.99). Item N of 2026-10-01 measures
the build-vs-build drift (`scripts/experiments/eval_delta_ingest_twin_drift_baseline.py`,
results `data/eval_results/delta_ingest_twin_drift_baseline_20261001.json`,
findings `spike/delta_ingest/TWIN_DRIFT_BASELINE_FINDINGS.md`), with its own
pre-registered rule on m = min over the two sets of mean overlap@10
build2-vs-build1. This document applies to each of item N's outcomes:

| Item N outcome | Meaning | Consequence here |
|---|---|---|
| **NOISE** (m ≤ 0.9915) | two stock builds of the same input disagree about as much as rebuild vs served | G1 holds. The fold quality bar F2 is noise-aware: per set, `bar_set = min(0.99, m_set) − 0.005`, where m_set is item N's build-vs-build mean overlap@10 on that set |
| **REAL LOSS** (m ≥ 0.998 and ≥ 99% identical top-10) | builds reproduce each other; the twin route as run loses fidelity | G1 FAILS; the twin route is BLOCKED for fold-in. Fold-in re-opens only through a remedy whose rebuild of the UNCHANGED shard 0 reaches overlap@10 vs served **≥ 0.99 on each set** (the M9 bar, unchanged): (R-a) rebuild with the served `input_token_to_id_map` (M9's named next step); (R-b) posting-layer-only fold from the unchanged `forward_data.bin` (`08_…` shortlist #2; needs the fork to build postings from an existing forward file, unverified). Meanwhile the trigger runs as a COMPACTION trigger only (09 L1) |
| **MIXED** (0.9915 < m < 0.998) | part noise, part real loss | Treated as REAL LOSS for blocking; the remedy bar becomes overlap@10 vs served ≥ m_set − 0.005 on each set (reach the noise floor, not 0.99) |
| **PARTIAL** (prefix arm only) or **NOT RUN** | drift measured on a 3 M-doc prefix, or not at all | Not decided: G1 does not hold; a full-shard drift run is required (≈ 30–45 min build under the lock, *est.*) |

If item N's own verdict and the table above ever disagree, both are recorded
and the stricter consequence governs.

**G2 — per-shard routing.** Today a generation is one SEISMIC shard for all
sections (`02_DESIGN.md` §4 item 11). Required code: a `route_shard` column
in the ledger's `docs` table = `shard_id(id, "sfu-seismic-plan01", 8)`
(`scripts/seismic_testbed/shard_spool.py:50`, the blake2b rule that built
plan01), written at `stage()` and backfilled for existing roots; an updated
W-id therefore routes to the shard holding its base copy. Gate bar:
**10,000 / 10,000** ids sampled (seed 20261001) from each served shard's doc
mapping route to that shard (all 8 shards; any miss fails G2 and stops the
track until explained).

**G3 — index write protection** (`docs/infrastructure/INDEX_WRITE_PROTECTION.md`).
`data/seismic_150m/` is irreplaceable and read-only, so the fold NEVER writes
it, not even at swap time:
- fold output goes to a side root on local disk (`<fold_root>/shard{s}/fold{k}/`;
  spike: `/home/vscode/work/delta_ingest/foldin/`), behind a guard that
  refuses any canonical path inside `<repo>/data/`, `/var/tmp/seismic_stage`
  or any `mmap_dir` of the served or staged manifests, non-local filesystems,
  symlinks and hard links (the `guard::check_writable` rule list of §3 item 1
  of that page), with a unit test per refusal;
- "swap-in" is a MANIFEST repoint, not a file swap: a new composed
  `shard_manifest.json` names *s′* at the side path in *s*'s position; the
  served base shard file stays where it is, untouched, as the rollback;
- publishing that manifest is an **operator step** (`cli.py publish-fold
  --shard s --fold k --confirm`), never automatic: the trigger only builds
  and reports `READY` with the F2/F3 evidence attached;
- the size+mtime baseline check of `data/seismic_150m`, `data/thinclient_index`
  and `/var/tmp/seismic_stage` runs before and after every fold and every
  publish; any difference aborts (bar: unchanged on 100% of runs);
- disk: each folded shard keeps its new f16 c1a dir (*est.* ~7.8 GB, the
  size of a twin; it is the next fold's input) + dv-v2 (*est.* ~5.5 GB) at
  the side root while the original stays; *est.* +13.3 GB per folded shard,
  +106 GB for all 8.

**G4 — per-leg newest-origin masks.** After *s* is folded, the SEISMIC copy
of a folded updated doc lives in *s′* (a base-position shard) while its
tantivy/meta/abstract copy still lives in a delta generation (§4: the
non-SEISMIC legs do not fold into the base). `keep_hit`/`shard_result_filter`
(`source/lib/thinclient/delta_layer.py` ~134–207) use one `superseded[id] →
origin` map and one livedocs bitset for all legs. Required code: *s′* gets
its own origin tag (`fold:s:k`) in `shard_origins`; `generations.json`
carries per-leg newest origins (`seismic` vs `sections`); the livedocs bit
for a folded doc stays set for the base tantivy/meta copy but the doc is
served from *s′* (filter keyed by origin, not by bit alone). Gate bar: unit
tests for every (leg × origin) case, and M1 gate-off parity **120/120** on
2 passes after the change (the code touches the gate-on path only, but M1 is
cheap insurance).

**G5 — the delta layer itself is eligible** (`09_…` §6). Fold-in can be
MEASURED before G5; it is adopted for serving only after G5.

**G6 — encoder calibration recorded** (not a gate on a value): mean nnz and
L2 norm of re-encoded vs stored vectors for ≥ 1,000 text-unchanged docs
(`08_…` §0.3; ~1 h *est.*), recorded before F2 runs because a systematic
shift would bias folded new docs against base docs inside one shard.

## 4. What folds, per served engine

| Engine | Fold-in action | Notes |
|---|---|---|
| **SEISMIC** | *s* → *s′* by the twin route (or a G1 remedy), output at the side root; served via manifest repoint (G3) | the only leg that leaves the delta; reduces live delta shards and removes dead copies from *s* |
| **tantivy BM25F** | NOT folded into base sections (no rebuild input: the base spool is gone, P1 in `02_DESIGN.md` §3). Folded docs stay in delta sections, which compaction consolidates into one long-lived "consolidated generation" built with `seismic=False` (supported by `build_generation`) | tax of that one generation is the fixed cost measured by 09 (x1 arm); its size dependence is §6 F0 |
| **meta.sqlite** | not folded (base is `immutable=1`); the consolidated generation's meta resolves folded docs delta-first as today | one meta probe for that generation |
| **Abstract sidecars** | not folded; consolidated generation's store(s) | 09 L2/L3 apply |
| **Livedocs / masks** | folded docs: SEISMIC origin → `fold:s:k`, sections origin unchanged (G4); deleted docs vanish physically from *s′* | `.liv` is rewritten at publish as today |
| **Dense leg** (OFF) | none | — |
| **RRF / CE rerank / `hydrate_scope`** | none; one vote per leg as before | F2 measures any rank change |
| **Result cache** | key rotates at the fold publish (R1 stamp) | one cold cache per fold |
| **Packer / personas / `manifest.json`** | none (shards are not sections) | — |
| **`reload()` / M5** | the publish drops the backend; *s′* is cold in page cache | F8 measures; the operator step includes a prefault of *s′* before publish |
| **Staging** (`SFU_SEISMIC_STAGE_DIR`) | *s′* is already on local disk; never staged via the helper (`_stage_shards_local` source == destination deletes, `INDEX_WRITE_PROTECTION.md` §2) | the harness sets the stage dir empty |

## 5. Data

- **Base shard:** shard 0 (M9 measured its rebuild chain there), f16 twin
  `data/seismic_150m/index/plan01/global_shard0of8.mmap` read-only (or the
  cmp-verified local copy `/home/vscode/work/inplace_update/twin_local/`),
  served dv-v2 shard 0 from the base manifest as A0.
- **Delta for the fold (shard-0-routed):** (i) corpus (b) docs routed to
  shard 0 (*est.* ~20k of 160,347, new works; vectors in the M4 roots'
  ledgers); (ii) the Stage-0 encoded subsample of the closed in-place spike
  under `/home/vscode/work/inplace_update/stage0/` (32,155 upserts + 1,131,292
  deletions routed to shard 0, per `06_…` results table; existence verified
  2026-10-01, format to be confirmed by the fixture builder — if unusable,
  (i) + corpus (a) shard-0 routed docs only, recorded as a deviation before
  the run). This is far below a 5% trigger (~940k docs); the fold's
  correctness, not the trigger level, is what F2–F5 test.
- **Queries:** QT = 120 topics (`data/sfu_eval_queries.json`, field `query`),
  QD = 100 diverse (M9's set), QA = 240 judged records
  (`dense_ablation_queries.json` + `dense_ablation_qrels_20260817.json`) for
  NDCG; E8 conventions (`encode_splade(q, "models/splade_onnx_fp16")`, top-64
  terms, k = k′ = 200, heap_factor 0.8, `SFU_SEISMIC_PREFLOOR=2`).
- **Results:** `data/eval_results/delta_ingest_foldin_<YYYYMMDD>.json`
  (keys F0–F8); findings `spike/delta_ingest/FOLDIN_FINDINGS.md`; harness
  `scripts/experiments/eval_delta_ingest_foldin.py` (to be written; copies
  §6 verbatim into its header before its first run).

## 6. Measurements and frozen bars

Arms: **A0** served shard 0, no delta; **L** (live) = A0 + the fold delta
served as delta generation(s) + masks; **F** (folded) = *s′* + masks with
the folded docs' SEISMIC origin moved (G4); **R** = M9's plain rebuild of
shard 0 without delta (exists: `/var/tmp/sfu_delta_D_20260929/`).

| # | Question | Metric | Bar (frozen) | Lock |
|---|---|---|---|---|
| **F0** | Size dependence of one consolidated generation's tax (calibrates (b)) | paired Δ(arm, n0) in-process as 09 §1.1, arms n0, n1 (160,347 docs, existing), g1M (one 1,000,000-doc generation of base docs re-ingested as updates with twin vectors, no GPU; corpus builder to write) | recorded; PASS-line for using a single consolidated generation as the long-lived sections tier: Δ(g1M) − Δ(n1) ≤ **8.0 ms** (CI upper bound). FAIL → the sections tier also needs a fold or a split, recorded | exclusive |
| **F1** | Trigger bookkeeping is exact | (a), (d), (c) computed by the trigger vs a brute-force recount over the ledger + livedocs on the F-fixture and on `root_n8` | identical on **100%** of 20 checkpoints (after each of 20 synthetic publishes) | none |
| **F2** | Quality parity of the fold | per set QT, QD: mean overlap@10 of F vs L on the federated SPLADE leg (8 shards, shard 0 = *s′* vs base 0 + delta), and on shard 0's own results; QA: NDCG@10 of F and L, paired bootstrap of mean(F − L) over 120 topics, 10,000 resamples, seed 0 | **Q-a:** overlap@10(F, L) ≥ `bar_set` (G1 NOISE: min(0.99, m_set) − 0.005; under a G1 remedy: 0.99) on EACH of QT, QD, federated; **Q-b:** overlap@10(F, L) ≥ overlap@10(R, A0) − **0.005** per set (the fold loses nothing beyond a plain rebuild); **Q-c:** the 95% CI of ΔNDCG@10 contains 0 or lies above 0; **Q-d:** mask leak 0 (no deleted id and no superseded base copy in any F result, 460 queries). PASS = all four | shared OK (no timing) |
| **F3** | Latency returns to n0 | `search_rrf` p50, 120 topics (M4 set), in-process arms n0, L (base + fold delta + consolidated sections tier), F (*s′* + consolidated sections tier), design and statistics = 09 §1 / §1.1 | p50(F) ≤ **1.05 × p50(n0)** AND bootstrap CI upper bound of Δ(F, n0) ≤ **+8.0 ms** (at most one generation's budget left after the fold); Δ(L, F) recorded | exclusive |
| **F4** | Fold cost per shard (profile `desktop_gpu`, quiet host) | wall per stage (dump, build, c1a, dotvbyte, publish), peak RSS (incl. `VmSwap`), scratch and output bytes | wall ≤ **90 min** total; peak RSS ≤ **10 GB** (< the 12 GB `desktop_gpu` abort); scratch ≤ **60 GB**; output ≤ **1.10 ×** (served dv-v2 + f16 twin bytes of *s*) × (docs of *s′* ÷ docs of *s*). Duty cycle at the adopted (a): Σ fold wall over 8 shards per (a)-period ≤ **25%** of that period (*est.* from F4 × §2) | exclusive (timing) |
| **F5** | Crash safety | 50 SIGKILL trials at uniform-random times over the fold wall on a reduced fixture (first 1,000,000 docs of twin 0 + the fold delta routed into it; fixture builder to write), plus 10 kills inside `publish-fold` on the full shard-0 fold output | **60 / 60**: (i) served state after restart is exactly the pre-fold or the post-fold state — every live delta doc routed to *s* is servable from exactly one SEISMIC origin, checked by state inspection + 200 own-id lookups per trial; (ii) the G3 baseline is unchanged; (iii) re-running the fold after a kill completes and its output passes F2 Q-a against L | none (fixture) |
| **F6** | Repeated folds do not compound drift | a second fold of *s′* from its own c1a output + a second delta batch (corpus (b) half not used in fold 1, or Stage-0 Q2 synthetic) | F2's Q-a and Q-b hold for fold 2 vs its live reference; overlap@10(fold 2, A0) on base-only docs recorded | shared OK |
| **F7** | Trigger values per profile | choose (a), (d), (b), (c) defaults from §1 candidates | rule (fixed): the SMALLEST (a) (most frequent fold) whose F4 duty cycle ≤ 25%; if the modelled tax (F0, 09 R1) at that (a)'s fold moment > 8 ms × the adopted `G_max`, the profile is flagged (no default ships ON); (d) = the smallest candidate ≥ the (d) value reached when (a) fires; (c) = 30 days unless F4 duty cycle at (c)-driven folds > 25%; (b) = 8 ms | none |
| **F8** | Reload after a fold publish | M5 metric on the F arm: `reload()` wall, first-query p50 vs warm p50, 5 reps, with the operator prefault of *s′* | the M5 bars, unchanged: reload ≤ **15 s**; first-query p50 ≤ **2 ×** warm p50 | exclusive |

Runtime *est.*: F0 ≈ 2.5 h (corpus build ~1 h + 3 arms in-process ~1.5 h);
F1 ≈ 15 min; F2 fold build ≈ 45–60 min + parity ≈ 30 min; F3 ≈ 1.5 h; F4
inside F2's build when run on a quiet host, else a separate ≈ 1 h; F5 ≈
60 × ~6 min on the 1M fixture ≈ 6 h (light, 2 cores) + 10 publish kills
≈ 30 min; F6 ≈ 1.5 h; F8 ≈ 30 min. At most one SEISMIC shard build at a time
on this host.

## 7. Resource profiles — one pipeline, dials only

Same code path on every profile (fold driver, guard, manifest repoint,
operator publish); only the dials of `spike/delta_ingest/profiles.py` change.

| Dial | `laptop` | `desktop_gpu` | `server` |
|---|---|---|---|
| fold enabled | only for shards whose *est.* build peak fits the 3 GB RSS cap: M9 peaked at 8.2 GB for 18.8 M docs, so *est.* ≤ ~6 M-doc shards (linear scaling assumed, unmeasured); a laptop-sized deployment (a Zotero or arXiv-subset corpus) has shards that small | yes | yes |
| fold threads | 2 | 8 (M9) | 16 |
| concurrent folds | 1 | 1 | ⌊48 GB ÷ (1.25 × F4 peak)⌋, *est.* 4 |
| scratch | the shard's jsonl (*est.* 2.1 KB/doc, M9: 38.9 GB / 18.8 M) | ≤ 60 GB | ≤ 60 GB × concurrency |
| trigger defaults | from F7 | from F7 | from F7; server may pick (a) = 0.02 (*est.* ~4 days per shard) |
| `os.nice` | +10 | +5 | 0 |

Source-agnostic: the trigger counts ledger rows and livedocs bits, whatever
adapter wrote them; non-W ids (`arxiv:…`, `zotero:…`) route by the same hash.
Scale: a GPU server folds all 8 shards of a quarter's churn in *est.* ~1.5 h
at concurrency 4; this host *est.* 6 h serial.

## 8. Kill criteria

- **Track KILLED** (CLOSED MEASURED, delta grows and compaction alone bounds
  latency): G1 = REAL LOSS or MIXED and both remedies miss their bar; or
  F4 wall > **3 h** or peak RSS > **12 GB** per shard on `desktop_gpu`; or
  F2 fails Q-a or Q-b after one fold rebuild with a corrected harness (a
  harness defect is fixed and re-run once; a model result is not); or F5
  has any trial with a served state that is neither pre- nor post-fold.
- **A parameter KILLED:** (b) if F0's model misses the measured Δ of 09's
  arms by > ±30%; (d) if F1 cannot compute per-shard dead counts exactly.
- **Sections tier FLAGGED, not killed:** F0 FAIL means the consolidated
  generation needs its own split/fold design (a new pre-registration).

## 9. Promotion of fold-in

Fold-in may be enabled for a deployment (trigger ON, publish still an
operator step) iff G1–G5 hold AND F1, F2, F3, F4, F5, F8 PASS AND F7 has
chosen the profile's values; F6 PASS is required before a second fold of the
same shard is published. Until then the default is OFF and the only bound on
delta growth is compaction (`09_…`).

## Addendum 2026-10-03 — owner decision on the F2 Q-a bar reading (recorded before F2 runs)

The owner chose **Reading A** (the G1 NOISE branch) on 2026-10-03, before any
fold was built: `bar_set = min(0.99, m_set) − 0.005`, i.e. **0.985** (QT) and
**0.980** (QD), with m_set the build-vs-build overlap of
`spike/delta_ingest/TWIN_DRIFT_BASELINE_FINDINGS.md`. Reading B (0.99) is
still computed and recorded by the harness
(`scripts/experiments/eval_delta_ingest_foldin.py`, `verdict_by_reading`),
but the F2 verdict is read on A (`--bar-reading A`). Nothing else in §6
changes.

## Addendum 2026-10-04 — owner decision on the level of F2 Q-b (recorded AFTER the runs it affects)

§6 gives Q-b as "overlap@10(F, L) ≥ overlap@10(R, A0) − 0.005 per set" and
does not say at which level; the harness fixed, before its first run, the
reading "shard-own AND federated". On that reading F2 read FAIL as computed
on fold 1 (2026-10-03) and again on fold 2 (2026-10-04, the one rebuild of
§8): QD shard-own 0.9780 vs 0.9820, federated 0.9980; every other bar PASS on
both folds (`spike/delta_ingest/FOLDIN_FINDINGS.md`).

The owner decided on 2026-10-04, **after both runs had been read**: **the
federated level is binding for Q-b; the shard level is not.** This is not a
pre-registered clarification — it was taken with the numbers known, and it is
recorded as such. The threshold (reference − 0.005) is unchanged; the
shard-own overlap and its pass flag stay recorded
(`--q-b-level federated` of `scripts/experiments/eval_delta_ingest_foldin.py`;
the default keeps the earlier reading so the 2026-10-03 record reproduces).

Read on the owner's level, **F2 = PASS on fold 1 and on fold 2** (Q-a, Q-b,
Q-c, Q-d; Q-d still on a fixture without deletions), and the §8 kill
condition "F2 fails Q-a or Q-b after one fold rebuild" is not met. F4's
memory bar, F1, F3, F5, F6, F8 are unaffected by this addendum.

## Addendum 2026-10-05 — owner amendment of the F4 memory bar (recorded AFTER the runs it affects)

§6 F4 froze "peak RSS ≤ 10 GB" from M9's 8.2 GB, a number M9's own record
says understated the working set (the build child was partly swapped; the
original build peaked at 9.92 GB). Three builds of the shard-0 fold were
measured (2026-10-03 and 2026-10-04, `spike/delta_ingest/FOLDIN_FINDINGS.md`):
peak process-tree VmRSS + VmSwap 12.11 GiB (fold 1), 13.13 GiB (fold 2, dump
change only), **11.37 GiB (fold 3, current code)**; every reading of fold 3
is above 10 GB (largest process 11.24, anonymous-only 10.32).

The owner decided on 2026-10-05, **with those numbers known**: **the F4
memory bar is amended to peak RSS ≤ 11.5 GB, read on the process-tree VmRSS +
VmSwap of the fold build as the recorder samples it** (GiB, the recorder's
unit; this also answers which number "peak RSS" is). This loosens a frozen
bar after measurement; it is recorded as an amendment, not a clarification,
and the original bar's verdict stays on record (FAIL on all three builds).
The value and its ground were proposed by the session's assistant and
accepted by the owner ("amend the bar"): a shard-rebuild cost of this size
is the normal cost of the delta + periodic-merge design
(`12_NEXT_SESSION_2026-10-05.md` §5, online research 2026-10-05), and 11.5
sits just above the one build of the current code.

Unchanged: the §8 kill line (peak RSS > 12 GB per shard on `desktop_gpu`) and
the profile abort (`max_rss_gb` 12.0); F4's wall, scratch and output bars;
the publish stage and the duty-cycle estimate, which no build record
includes yet.

Read on the amended bar: fold 3 **PASS** (11.37 ≤ 11.5, margin 0.13 GiB);
folds 1 and 2 FAIL (older code). The margin is thin: the peak is the
dotvbyte converter's last 2 s sample and moved between builds (fold 2 and
fold 3 both read 11.24 GiB for that process); a build that reads above 11.5
fails F4 again, and one above 12 meets the kill line.
(`data/eval_results/delta_ingest_foldin_20261004.json` key
`F4_amended_bar_20261005`; the recorder writes both flags from now on.)

## Addendum 2026-10-08 — implementation readings of §1 (a)/(c)/(d) and of F1 (recorded BEFORE the F1 run)

The trigger bookkeeping is `spike/delta_ingest/trigger.py`, called by
`generation.publish()` after `generations.json` is written; it writes
`<delta_root>/trigger.json` (+ one line of `trigger_log.jsonl`) and only
reports. These readings fix what the code counts; none changes a threshold or
a bar.

- **Base docs of s** = `n_docs` of position s in the base shard manifest that
  `publish()` used (after a published fold, s′'s record).
- **(a)** counts ledger rows with status `live`, `route_shard = s` and
  `seismic_origin IS NULL`: a doc whose newest SEISMIC copy is already inside a
  published fold of s does not weigh on the delta leg, so it is not counted
  (otherwise (a) would fire again as soon as the 24 h hysteresis ends).
- **(c)** = now − MIN(`last_seen`) over the same rows (`last_seen` = stage
  time of the current copy, the `staged_at` of `foldin`).
- **(d), no published fold of s** = distinct base ordinals set in the livedocs
  bitset whose id routes to s. With no ordinal arrays (no bitset) the ledger
  reading is used — tombstones with `in_base=1` plus live `in_base=1` docs,
  routed — and the record says `d_source = "ledger"`.
- **(d), after a published fold k of s** (snapshot T): only copies dead in s′
  count — a live `in_base=1` doc with `last_seen > T` that was a fold member
  or first seen after T, or a tombstone with `ts > T` whose id was a member or
  had no `docs` row first seen at or before T. Residual edge, not handled: an
  id tombstoned both before and after T with no `docs` row. F1's checkpoints
  publish no fold, so this branch is covered by unit tests
  (`scripts/tests/test_foldin_trigger.py`) and NOT by F1.
- **(b)** is not implemented (needs F0); `SFU_DELTA_FOLDIN_TAX_MS` is ignored
  and every record carries `tax_ms: null` and a `tax_hook` note.
- **Dials:** env only (`SFU_DELTA_FOLDIN_FRAC`, `_DEAD_FRAC`, `_MAX_AGE` in
  days); unset or empty = OFF; no profile default until F7.
- **F1 "synthetic publish"** = a ledger mutation batch on a copy (upserts of
  new ids, updates of base ids, deletions of base ids, deletions of live delta
  ids) staged into the buffer, then `publish()` with the full local ordinal
  arrays (`/var/tmp/sfu_delta_C_20260929/ords`) so a bitset is written; no
  generation is frozen (buffer docs are live delta docs for (a)). The
  brute-force recount is an independent path: (a)/(c) from every `docs` row
  routed with `scripts/seismic_testbed/shard_spool.py` `shard_id` (not the
  stored `route_shard`), (d) by decoding the published `.liv` (crc checked),
  mapping set ordinals to W-ids through `wids.npy` and routing them the same
  way; base docs from the manifest file read directly. "Identical" = equal
  integer numerators, equal denominators, and equal `oldest_staged_at` floats
  per shard; fractions follow. The copies hold the ledger and each
  generation's `generation.json` only (what `publish()` reads); the originals
  are never opened for writing. The `root_n8` copy gets `backfill-routes`
  (the original has no route columns).

## Addendum 2026-10-08 — the deletions fixture for Q-d (recorded BEFORE its fold is built)

§5 (ii) names the Stage-0 encoded subsample as delta input; until now every
fold ran on `fixture_n8` (0 tombstones, 0 superseded), so Q-d tested only
double-serving. The Stage-0 format is usable (no deviation from §5 is
needed): `/home/vscode/work/inplace_update/stage2/docs` holds the 32,155
encoded upserts (SPLADE vectors in shard 0's token ids, encoder text and year
per doc) and the 1,131,292 deleted shard-0 rows of 2026-06-17 .. 2026-09-15.

**Fixture** `/home/vscode/work/delta_ingest/foldin/fixture_n8_del`, built by
`scripts/experiments/delta_ingest_foldin_del_fixture.py` through the product
ledger path (`IngestLedger.delete` / `stage`, `freeze_buffer`, `publish` with
the base ordinal arrays `/var/tmp/sfu_delta_C_20260929/ords`, so the masks are
the livedocs bitset), record `build_fixture.json` beside it:
copy of `fixture_n8` (fold tables emptied) + **1,131,292 tombstones** (all
routed to shard 0, all in base) + the 32,155 upserts as one new generation
g0009, all routed to shard 0: **8,465 superseded base docs**, **20,112
re-staged delta docs** (every corpus (b) doc routed to shard 0 is also a
Stage-0 upsert — corpus (b) was cut from the same part files — so its g0001–
g0008 copy is now a superseded delta copy) and 3,578 new docs. Livedocs
popcount 1,139,757 (1,131,292 deleted + 8,465 superseded; 0 deletes without
an ordinal). Live delta docs routed to shard 0: 32,155. Expected docs of s′ =
18,799,322 − 1,131,292 − 8,465 + 32,155 = **17,691,720**. The upsert records
carry the encoder text as `title` and the year only (as the in-place bench's
A1 arm built them); both arms serve the same records, so F-vs-L parity is
unaffected.

**This is a NEW fold (different delta), not a rebuild of fold 1**: its fold
root is `/home/vscode/work/delta_ingest/foldin_del` (fold 1 of that root). A
Q-a or Q-b failure on it is a result of this fold. The §8 clause ("F2 fails
Q-a or Q-b after one fold rebuild with a corrected harness") is applied to it
as to any fold: a harness defect is fixed and re-run once, a model result is
not; the kill is the owner's call and is not decided by the run.

Bars, unchanged: Q-a Reading A (0.985 / 0.980), Q-b at the federated level
against the same base-only reference overlap@10(R, A0) (0.9858 / 0.9870 −
0.005; R and A0 do not depend on the delta), Q-c as frozen, **Q-d = 0 leaks
over 460 queries** — now with real tombstones, base-superseded and
delta-superseded copies. F4 on the amended bars (wall ≤ 90 min, tree peak ≤
11.5 GB, scratch ≤ 60 GB, output ≤ 1.10 × (served dv-v2 + f16 twin) × docs
of s′ ÷ 18,799,322; kill line 12 GB). Result keys `F4_build_fold_del`,
`F2_fold_del` in `data/eval_results/delta_ingest_foldin_20261008.json`.

## Addendum 2026-10-08 — F3/F8 implementation reading (recorded BEFORE either run)

Harness `scripts/experiments/eval_delta_ingest_foldin_f3f8.py` (rows F3 and F8
copied verbatim in its header); launcher
`/home/vscode/work/delta_ingest/foldin/f3f8/run_f3f8.sh` (exclusive latency
lock around setup → smoke → F8 → F3; it starts only after the deletions-fixture
F2 of the addendum above has written its result). Results
`data/eval_results/delta_ingest_foldin_f3f8_<YYYYMMDD>.json`, keys `setup`,
`F8`, `F3`. No bar changes; these readings fix what the rows leave open.

**Common.** Every root is a COPY under `…/foldin/f3f8/` (never `fixture_n8`,
never a served root, never `data/`). All arms serve the base from the staged
manifest `/home/vscode/work/inplace_update/m4/base_manifest.json` (local disk,
as 09's n0 and roots), not the repo-data manifest `fixture_n8` was published
over. Delta arms run the fallback stack's levers L3 + L4 + L5
(`SFU_DELTA_ABS_ROUTE`, `SFU_BM25F_PARSE_ONCE`, `SFU_SEISMIC_DELTA_GROUP` = 1),
layout `per_base_section`, parallel federation. `publish-fold` now prefaults
the fold's served dir before the repoint (the operator prefault of §4; commit
c5998e72); its seconds are recorded.

**F3 arms.** The fold delta is the 160,347 corpus (b) docs of `fixture_n8`.
- **n0**: gate off, staged base (09's n0).
- **L** = base + fold delta + consolidated sections tier: 09's `root_n8c`
  (the same 160,347 docs compacted into ONE generation that carries its
  SEISMIC shard and its sections) + L3/L4/L5 — the `x8c` arm of 09 R1/R3.
- **F** = s′ + consolidated sections tier: a copy of `fixture_n8` compacted
  (`cli.py compact --gens 1..8 --no-seismic`) into ONE generation with no
  SEISMIC shard, then `cli.py publish-fold --shard 0 --fold 1 --confirm`
  (fold 1 = the fold that passed F2): s′ at position 0, staged base shards 1–7,
  no delta SEISMIC shard, folded docs' SEISMIC origin `fold:0:1`.
- Deviation, stated: only shard 0 is folded, so in F the delta docs routed to
  shards 1–7 (≈ 140k of 160,347) have no SEISMIC copy anywhere. F is therefore
  the latency of the post-fold steady state (no delta SEISMIC shard), not a
  servable mixed state. F3 measures latency only; quality is F2's.
- Recorded beside the bar: **n0x** (n0 + L4, the one lever that acts on the
  base, 09's reference), Δ(F, n0x), Δ(L, F), Δ(L, n0).
- Design and statistics = 09 §1/§1.1 through `eval_delta_ingest_m4f.py
  inproc` (one process, one retriever per arm + a prime retriever, 1 warm-up +
  2 measured passes over the 120 M4 topics, per-query shuffled arm order, quiet
  gate, memory guard). p50 = pooled over both measured passes; Δ = median of
  paired per-(pass, topic) differences, 95 % CI by topic-cluster bootstrap
  (2,000 resamples, seed 20261001). Bar as frozen: p50(F) ≤ 1.05 × p50(n0) AND
  CI upper bound of Δ(F, n0) ≤ +8.0 ms. Not read unless the run is COMPLETE
  and healthy.

**F8.** The F arm of F2 (s′ + the 8 delta generations) on a copy of
`fixture_n8` republished over the staged base, fold 2 (also F2 PASS at the
federated level, 2026-10-04) — fold 2 rather than fold 1 because the composed
fold manifest is never overwritten and F3's root composes fold 1's. One
process (M5 design), L3/L4/L5 on:
- warm-up pass on the pre-fold state;
- **rep 1** = the real operator step (`publish-fold`, prefault included), then
  `reload()` timed, first query + 9 recovery queries;
- warm-up + **warm pass on the post-fold state** — warm p50 = that pass (the
  state the first query is served from);
- **reps 2–5** = restore the pre-fold files (generations.json, the composed
  manifest it names, any livedocs it names) → `reload()` → one query
  (rollback, recorded) → prefault s′ → restore the post-fold files →
  `reload()` timed → first query + 9 recovery. Each restore changes the stamp,
  so the backend is dropped every time (asserted);
- 2 controls (reload without a change), recorded.
- First queries: topic (rep − 1) × 24 of the 120, as M5. Bars as frozen: max
  `reload()` ≤ 15 s over the 5 reps; median first-query ms ≤ 2 × warm p50.
  The same-topic paired ratio is recorded.

## Addendum 2026-10-08 — F0 implementation readings (recorded BEFORE the g1M build and the F0 run)

Harness `scripts/experiments/eval_delta_ingest_foldin_f0.py` (row F0 copied
verbatim in its header; unit tests `scripts/tests/test_foldin_f0_builder.py`);
launcher `/home/vscode/work/delta_ingest/foldin/f0/run_f0.sh`, which starts
only after the F3/F8 launcher has written `…/foldin/f3f8/F3F8_DONE` (host order
deletions → F3/F8 → F0 → F5) and always writes `…/foldin/f0/F0_DONE`. Result
key `F0` in `data/eval_results/delta_ingest_foldin_f0_<YYYYMMDD>.json`. No bar
changes; these readings fix what the row leaves open.

**g1M corpus (1,000,000 base docs of shard 0, re-ingested as updates).**
- **U** = every shard-0 base doc that the Stage-0 sample of the closed
  in-place spike (10 % of the 2026-06-17 .. 2026-09-15 OpenAlex
  `updated_date` part files, `/home/vscode/work/inplace_update/stage0/`) saw
  updated and in slice (`partsout_f10/*.npz`: `rows ≥ 0` and `in_slice`;
  517,185 expected). Text = that snapshot record (newest part wins) through
  the product adapter `normalize_openalex_work`.
- **F** = fill to exactly 1,000,000 with shard-0 base docs whose ordinal
  section is `social_sciences__recent` and that its abstract sidecar holds,
  minus U, in a seeded permutation (seed 20261008). Text = base meta row +
  sidecar abstract via `seed.base_record`. Deviation, stated: base text is
  local only for that one section (the other nine have no local sidecar), so
  about half the corpus sits in one base section where real updates spread
  over all ten. U keeps the real spread for the other half.
- Vectors for U and F = the doc's stored f16 vector in twin 0 (the local copy,
  `BaseVectorStore` exact-or-refuse); a refused doc is dropped and counted,
  never re-encoded. No GPU. U's snapshot text is newer than the stored
  vector's text; F0 measures latency, not quality.
- All docs are routed to shard 0 (vectors exist locally only for twin 0), so
  the livedocs bits of the superseded base copies concentrate in shard 0
  (1,000,000 of 18,799,322 = 5.3 %) instead of spreading over 8 shards.

**Root** `/home/vscode/work/delta_ingest/foldin/f0/root_g1M`: a NEW ledger,
all 1,000,000 staged with `in_base=1`, frozen as ONE generation by the product
`freeze_buffer` — layout `per_base_section`, **`seismic=True`** (the row says
"with twin vectors", and without a delta SEISMIC copy the superseded docs
would vanish from the SPLADE leg, a state no serving path produces before a
fold). The consolidated tier of §4 drops that shard after a fold, so F0 reads
an **upper bound** on the post-fold sections-tier tax; the delta SEISMIC
shard's own share is recorded from the leg attribution
(`seismic_delta_shard_sum`). Base manifest = M4's staged manifest
(`/home/vscode/work/inplace_update/m4/base_manifest.json`, as `root_n1` and
F3); base ordinals `/var/tmp/sfu_delta_C_20260929/ords`, so the superseded base
copies are masked by the livedocs bitset (`root_n1` has no masks: its docs
are new works). Profile `desktop_gpu` with `max_rss_gb` raised 12 → 40 for
this fixture build only (it is not a fold and not an F4 record); build wall,
tree peak and bytes are recorded under `build_g1M`.

**Arms and statistics** (09 §1/§1.1 through `eval_delta_ingest_m4f.py
inproc`: one process, a retriever per arm + a separate prime retriever, 1
warm-up + 2 measured passes over the 120 M4 topics, per-query shuffled arm
order, quiet gate, memory guard, parallel federation):
- **n0x** = gate off + L4 (the stack's one base-acting lever; 09's reference);
- **x1** = `m4/root_n1` (160,347 docs, 1 generation) + L3, L4, L5;
- **xg1M** = `root_g1M` + L3, L4, L5.
The bar quantity Δ(g1M) − Δ(n1) is read per (pass, topic) unit as
t(xg1M) − t(x1), which equals Δ(g1M, n0x) − Δ(n1, n0x) unit by unit; median
and 95 % topic-cluster bootstrap CI (2,000 resamples, seed 20261001). **PASS
iff the run is COMPLETE and healthy AND the CI upper bound ≤ 8.0 ms**; else
FAIL (sections tier flagged, §8), or NOT READ if incomplete. Recorded beside
it: Δ(x1, n0x), Δ(xg1M, n0x), per-leg median differences, and the
coefficient **c = median ÷ 0.839653** (ms per million delta docs added) for
§1 (b)'s model T = a + b·G + c·D, with b from the 09 R1 F-SLOPE records.

## Addendum 2026-10-08 — F5 implementation readings (recorded BEFORE any F5 trial)

Harness `scripts/experiments/eval_delta_ingest_foldin_f5.py` (row F5 copied
verbatim in its header); launcher `/home/vscode/work/delta_ingest/foldin/f5/run_f5.sh`.
Results `data/eval_results/delta_ingest_foldin_f5_<YYYYMMDD>.json` key `F5`,
per-trial rows in `…/foldin/f5/rows.json`. No bar changes; these readings fix
what the row leaves open.

**Code fixed BEFORE any trial, found by review while writing the checker**
(commit 60ba0fc1, 7 tmp-tree tests in `scripts/tests/test_foldin_f5_crash.py`).
F5 measures the code at the launcher's commit, which includes them:
1. `generation.publish` rewrote `<delta_root>/shard_manifest.json` in place
   BEFORE `generations.json`. A kill between the two renames paired the new
   composed manifest with the old masks; on `fixture_n8` (all fold members are
   new works, absent from `superseded`) every member would be served from both
   s′ and its delta generation — a state neither pre- nor post-fold. The test's
   negative control reproduces it (6/6 docs double-served). Now the manifest goes
   to a NEW file per publish (`shard_manifests/shard_manifest-<stamp>.json`) and
   `generations.json`, written last, names it: one commit point.
2. `compose_fold_manifest` refused any existing output, so `publish-fold`
   killed after composing but before its ledger commit could never be re-run.
   An existing manifest with the same source and the same records is now reused;
   any other is still refused.
3. `build_fold` took the fold number from the ledger only, so a build killed
   between `make_fold_dir` and its ledger row left a dir that blocked every
   re-run ("fold numbers are never reused"). `next_fold` now also skips existing
   `shard{s}/fold{k}` dirs.

**Reduced fixture.** First 1,000,000 docs of twin 0 (the cmp-verified local
copy), dumped in twin row order in the fold dump's format and built by the twin
route with the twin's pinned token map (f16 c1a = the fold input, + dv-v2 =
served); a 1-shard base manifest naming it. Fixture root = a copy of
`fixture_n8`'s ledger (sqlite backup, fold tables emptied) + copies of
g0001–g0008, published once over the reduced base: the pre-fold state. "The fold
delta routed into it" = the 20,112 `fixture_n8` docs routed to shard 0 (all new
works, so the fold drops no base row; docs of s′ = 1,020,112). Docs routed to
shards 1–7 stay in the delta generations, served as before. Fold root
`…/foldin/f5/foldroot`.

**Kill.** SIGKILL to the whole process group of the `cli.py fold-build` /
`publish-fold` child at once (the CLI, its dump workers and its Rust converter
children): the closest model of a host crash or OOM kill available here (no
cgroups). Kill times uniform on [0, W]: W = mean wall of two clean folds of the
fixture (`calibrate`), seed 20261008; for publish, [0, W_p] with W_p = wall of
one clean reference publish on a copy, seed 20261009. A trial whose child exits
before its kill time is recorded `finished_before_kill` and replaced by the next
draw (at most 25 per phase); replacements are listed in the result. "Restart" =
a fresh `DeltaLayer` + SEISMIC backend over the root, with no repair step run.

**(i) — exactly the pre-fold or the post-fold state.** All three must hold:
(a) the served-state digest (composed-manifest records, generations, mask
hashes, livedocs facts, base manifest; paths normalised to the root; stamp,
publish time and manifest file name left out) equals the pre-fold digest taken
from the root just before the trial, or the post-fold digest of the clean
reference publish; (b) state inspection: every live delta doc routed to shard 0
is kept at exactly one served position after the product per-shard filter
(physical membership from the served shards' document mappings), at the
expected origin (pre: its delta generation; post: `fold:0:k` for the fold's
members, its generation otherwise); (c) 200 own-id lookups (sample seed
20261008; the doc's own top-64 vector as the query through the product loader
and filter, per-shard k = k′ = **1000**): no doc returned from two positions or
from an unexpected origin, and the set of docs not returned equals the
reference state's. k = 1000, not the E8 200: the smoke showed a quarter of the
delta docs rank 384–778 on their own vector (inner product favours heavier docs
on the same terms), so k = 200 would leave a quarter of the lookups unable to
see a double. Base positions ≠ 0 are not searched (G2: an id routed to shard 0
cannot be in them). A trial reading neither is recorded as the §8 kill
criterion; it is never fixed and re-run silently.

**(ii)** G3 baseline (`foldin.default_baseline_roots`) snapshot before the
trial; unchanged after the kill AND after the re-run.

**(iii) fold-build trials:** the re-run (a new fold number) completes (rc 0,
state `built`) and its F arm (preview root) passes Q-a against L on QT + QD (220
queries, the reduced fixture's federated SPLADE leg, E8 conventions). Bar =
Reading A (owner, 2026-10-03), bar_set = min(0.99, m_set) − 0.005, with m_set =
mean overlap@10 between the two clean calibration folds' F arms (§3 G1's
build-vs-build rule applied to this fixture; item N's m_set belongs to the full
shard). Reading B (0.99) is recorded beside it. If either clean fold itself
fails that Q-a, (iii) is NOT READABLE on this fixture and the verdict says so;
no bar changes. **publish trials:** the re-run of `publish-fold` completes, the
served-state digest after it equals the clean post-fold digest, and the fold dir
(size + mtime of every file) is unchanged. Q-a is inherited from F2 fold 1:
the published output is fold 1 itself, unchanged bytes (Q-a PASS 2026-10-04,
federated, Reading A).

**Publish trials' roots.** A master copy of `fixture_n8` (ledger backup +
g0001–g0008 copied once) under `…/foldin/f5/pub/master`; per trial the ledger is
backed up again and the generation dirs symlinked to the master's copies. Each
copy is published over M4's staged base manifest
(`/home/vscode/work/inplace_update/m4/base_manifest.json`, the base F3/F8 uses,
so the shared composed manifest `…/foldin/manifests/shard_manifest.fold_s0_k1.json`
comes out identical and is reused). Fold 1 of shard 0 (`…/foldin/shard0/fold1`)
is marked READY on the copy. If the shared manifest exists with different
content, the harness pre-composes its own under `…/foldin/f5/pub/manifests/` and
records that per trial.

**Run.** The launcher waits for `…/foldin/f3f8/F3F8_DONE` AND
`…/foldin/f0/F0_DONE`, then holds the latency lock SHARED for the whole run (an
exclusive latency run excludes it). Threads 4, dump workers 2; wall *est.*
~6.5 h. Smoke of 2026-10-08 (30,000-doc base, 10 queries per set, 3 + 2 trials,
`…/foldin/f5_smoke/`): plumbing only, 5/5, not a result.

## Addendum 2026-10-09 — F7 implementation reading (recorded BEFORE F7 is computed)

F7 is a computation (no lock, no index). Script
`scripts/experiments/eval_delta_ingest_foldin_f7.py`, result key `F7` in
`data/eval_results/delta_ingest_foldin_f7_20261009.json`. No bar changes;
these readings fix what the row leaves open.

- **Fold wall per shard** = max measured F4 wall (fold 3, 1,431.2 s) + the
  F8 `publish-fold` wall (15.1 s) = 24.1 min. Σ over 8 shards (serial;
  concurrency does not change a sum) = 3.21 h. Same number for `server`
  (no server measurement exists; *est.*, an upper bound for a faster host).
  `laptop`: fold disabled for shards above *est.* ~6 M docs (§7), so F7 is
  NOT APPLICABLE to this corpus's 18.8 M-doc shards on `laptop`.
- **(a)-period** = days from a fresh fold until (a) fires, from §2's table,
  **as coded** (the governing stream; the text filter is not built). The
  text-filtered column is computed and recorded beside it, not used.
- **Duty cycle** at (a) = 3.21 h ÷ (24 h × period).
- **Tax model** T(D, G) = Δ(x1, n0x) + b × (G − 1) + c × (D − 0.160347),
  with Δ(x1, n0x) = +6.60 ms and c = 21.354 ms per million delta docs from
  the F0 run (same harness, same day), b = 1.308 ms/gen = `09` R1 F-SLOPE on
  the fallback stack (`R1_per_base_section_repeat`). D is in millions and
  counts **every live delta doc of every shard, including the docs held only
  by the never-folding sections tier** (§4: tantivy/meta/abstract copies stay
  in the delta after a fold). c carries the delta SEISMIC share too, which is
  right at a fold moment (the delta SEISMIC shards are still live then).
- **"That (a)'s fold moment"** = the FIRST fold moment after a full build
  (the most favourable one): routing is uniform, so all 8 shards reach (a)
  together and D = 8 × a × 18,799,322 / 10⁶. G = the adopted G_max =
  `max_live_gens` of the profile (8 on every profile, `profiles.py`), the
  worst served state L1 allows. Flag iff T > 8 ms × G_max = 64 ms. Recorded
  beside it, no verdict: T at the k-th fold round (D grows by the same step
  each round, because folded docs stay in the sections tier), T with c at its
  CI bounds (12.62 / 27.63), and T at G_max 1 and 4.
- **(d)** = the smallest §1 candidate ≥ the dead fraction reached when (a)
  fires = 0.367 %/day as coded × period. **(c)** = 30 days unless the duty
  cycle of (c)-driven folds (3.21 h per 30 days) > 25 %. **(b)** = 8 ms.
- A FLAG means no default ships ON for that profile; the chosen values are
  still recorded.

## Addendum 2026-10-09 — F6 implementation reading (recorded BEFORE the F6 fixture and fold are built)

- **Live state before the second fold** (`/home/vscode/work/delta_ingest/foldin_f6/fixture`):
  a copy of `fixture_n8` republished over the staged base manifest
  (`m4/base_manifest.json`, as F3/F8), fold 1 marked READY on its F2 evidence
  (2026-10-03/04, federated Q-b) and published with `publish-fold` (its
  composed manifest is the identical one F3 composed and is reused), THEN the
  second delta batch applied through the product ledger path by
  `scripts/experiments/delta_ingest_foldin_del_fixture.py --keep-folds` (the
  fold tables are kept so publish serves s′ at position 0).
- **Second batch — deviation from the row, stated now:** the row names
  "corpus (b) half not used in fold 1, or Stage-0 Q2 synthetic". Fold 1
  used ALL corpus (b) shard-0 docs, and no Q2 data exists locally, so the
  batch is the Stage-0 Q1 subsample (the deletions fixture's batch):
  1,131,292 tombstones, 32,155 upserts — which re-update all 20,112 fold-1
  members (a fold origin superseded by a newer generation: a stricter case
  than the row's), supersede 8,465 base docs and add 3,578 new docs.
- **Fold 2 of s′** = `fold-build` with `--fold-input` = fold 1's own c1a
  output `/home/vscode/work/delta_ingest/foldin/shard0/fold1/fold.mmap`,
  token map pinned to the twin's (as every fold), fold root
  `/home/vscode/work/delta_ingest/foldin_f6` (the ledger numbers it fold 4;
  it is "fold 2 of s′"), through the F4 recorder (shared lock; its F4
  numbers are recorded, not read against F4).
- **Bars read:** F2 Q-a and Q-b exactly as the owner readings stand
  (`--bar-reading A --q-b-level federated`), L = the fixture (s′ + delta +
  masks), F = the preview of fold 4; Q-b's reference overlap@10(R, A0) is the
  same drift-run reference as every F2. **F6 PASS = Q-a AND Q-b PASS.** Q-c
  and Q-d are computed and recorded beside it, not part of F6's verdict.
- **Recorded, no bar:** overlap@10(fold 2, A0) on base-only docs = per QT/QD
  query, F's shard-own top-10 minus every id the fixture ledger knows (docs
  + tombstones), against A0's ranked list (served shard 0, the drift run's
  `q_served_dv.json`) minus the same ids, cut to the same length, mean per
  set. The same number for the deletions fold's F arm (built from the twin;
  the SAME doc set, 17,691,720 docs, since `fold_plan` drops every
  ledger-known shard-0 id and re-adds every live shard-0 delta doc), and
  overlap@10 between the two F arms' shard-own and federated lists (one fold
  vs two folds of the same docs) — the direct compounding-drift reading.

