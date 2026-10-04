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
(`src/lib/thinclient/delta_layer.py` ~134–207) use one `superseded[id] →
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
