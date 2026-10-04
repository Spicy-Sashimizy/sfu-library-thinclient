# Fold-in prerequisite gates G2, G3, G4, G6 (doc 10 §3)

**Status:** ACTIVE

Agent FOLD, third wave of the delta-ingest dispatch, 2026-10-01 (16:48–17:22Z, resumed 22:17Z).
Spec: `docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md` (FROZEN; not
edited). G1 already holds (agent DRIFT, NOISE, 2026-10-01 16:45Z,
`TWIN_DRIFT_BASELINE_FINDINGS.md`). This file records the code and the bars
of G2, G3, G4 and G6. **No fold was built and no F-bar was run** in this
session (§6 gives the commands).

Harness: `scripts/experiments/eval_delta_ingest_foldin_gates.py`.
Results: `data/eval_results/delta_ingest_foldin_gates_20261001.json`.
Code: `spike/delta_ingest/routing.py`, `spike/delta_ingest/foldin.py`,
`spike/delta_ingest/ledger.py`, `spike/delta_ingest/generation.py` (two small
hunks), `spike/delta_ingest/cli.py` (three subcommands),
`src/lib/thinclient/delta_layer.py` (G4).
Tests (new files, tmp trees only): `scripts/tests/test_foldin_routing.py` (6),
`test_foldin_guard.py` (21), `test_foldin_masks.py` (16), `test_foldin_e2e.py` (1).

## Summary

| Gate | Verdict | Numbers | Commits |
|---|---|---|---|
| G2 per-shard routing | CODE DONE; **gate bar NOT RUN** (queued, shared lock) | backfill on copies: 50,000 + 160,347 rows routed, 0 mismatches; equality with the plan01 rule on 3,005 ids | 58970753 (code), 922e125a (harness + backfill results) |
| G3 index write protection | CODE DONE, unit bars PASS; the "unchanged on 100% of runs" bar has no real fold/publish run yet, so NOT RUN | 21 guard tests + 1 toy end-to-end, all pass | 58970753, 07ef52c0 |
| G4 per-leg newest-origin masks | CODE DONE, unit bar PASS; M1 120/120 × 2 passes after the change **PASS 2026-10-03** (code 8dcde712, `data/eval_results/delta_ingest_M1_2pass_20261003.json`) | 16 tests; no-fold filter equal to the pre-G4 code on 2,000 / 2,000 random cases | **11527c59** |
| G6 encoder calibration (recorded, not gated) | **PARTIAL**: nnz recorded (O14), L2 norm NOT RUN (queued GPU run) | nnz 83.18 re-encoded vs 83.00 stored, 1,882 docs (O14, 56d38a39) | 922e125a (harness) |

**Queued, not run (owner rule 2026-10-01: no agent waits on a lock).** At
22:18Z the exclusive lock was held by EVAL's M4 sequential run (until about
00:20Z). G2 and G6 sit in a detached self-queuing script:
`/home/vscode/work/delta_ingest/foldin/fold_queue.sh`, log
`/home/vscode/work/delta_ingest/foldin/fold_queue.log`, marker
`SHARED_RUNNING_FOLD`. It waits for no `EXCL_WAITING_*`, fewer than 2
`SHARED_RUNNING_*` and MemAvailable >= 14 GB. G6 also waits for an idle GPU
and no O14 process. It runs each step under `flock -s` and gives up as NOT
RUN 10 min before 06:00Z. Both steps write
`data/eval_results/delta_ingest_foldin_gates_20261001.json` (keys
`G2_routing`, `G6_encoder_calibration`). The JSON is not committed by the
script. To read the G2 verdict:

```
.venv/bin/python3 -c "import json;g=json.load(open('data/eval_results/delta_ingest_foldin_gates_20261001.json'))['G2_routing'];print(g['verdict'],g['total_misses'],[p['routed_to_own_shard'] for p in g['per_shard']])"
```

## G2 — per-shard routing

- `spike/delta_ingest/routing.py` `route_shard(id)` = blake2b-8(seed + id) mod
  8, seed `sfu-seismic-plan01`. It is the rule of
  `scripts/seismic_testbed/shard_spool.py:50`. A test asserts equality with
  the original on 3,005 ids (W-ids, `arxiv:`, `zotero:`, empty).
- Ledger `docs.route_shard` is written at `stage()` for ledgers created at or
  after 58970753. An existing ledger is never altered on open. It is
  migrated only by `backfill_routes()` / `cli.py backfill-routes`
  (idempotent; also adds `seismic_origin` and the index
  `docs_route(route_shard, status)`).
- Backfill on COPIES (sources opened `mode=ro&immutable=1`, size + mtime
  unchanged, 2026-10-01 17:04Z):
  `/home/vscode/work/delta_ingest/corpus_a/root` gave 50,000 rows routed and
  0 mismatches. M4 `root_n8` gave 160,347 rows routed and 0 mismatches; live
  docs per shard 20,112 / 20,030 / 20,124 / 20,047 / 20,109 / 19,840 /
  20,246 / 19,839. Shard 0's 20,112 matches doc 10 §5 *est.* ~20k. In both
  copies the second backfill was a no-op.
- **Gate bar (10,000 / 10,000 per served shard, seed 20261001): NOT RUN,
  queued.** Method (`g2-routing`): reads only
  `document_mapping_{offsets,strings}.bin` of the 8 dirs of the serving
  default manifest (`seismic_c25_shards_150m_mmap_e5_v2.json`). It does not
  load the index; it uses memmap offsets and one `pread` per id. One numpy
  `default_rng(20261001)` draws `choice(n, 10000, replace=False)` per shard
  in manifest order. Not run in this session: the shared slots were taken
  16:48–17:22Z, and from 22:17Z the exclusive lock was held.

## G3 — index write protection

All in `spike/delta_ingest/foldin.py`.

- **Side root**: `<fold_root>/shard{s}/fold{k}/` (default
  `/home/vscode/work/delta_ingest/foldin/`). `make_fold_dir` creates it with
  its own `.fold_work_dir` sentinel. Fold numbers are never reused.
- **Guard** (`check_target`, `check_writable`), the refusal list of doc 10 G3
  and `INDEX_WRITE_PROTECTION.md` §3 item 1, one tmp-tree test each in
  `scripts/tests/test_foldin_guard.py`:
  inside `<repo>/data/`; inside `/var/tmp/seismic_stage`; inside an
  `mmap_dir` of the served manifests (`SFU_SEISMIC_SHARD_MANIFEST` + the
  serving default ladder) even outside `data/`; inside an `mmap_dir` of the
  staged manifest; a fold root that itself lies in a protected tree; outside
  the fold root or equal to it; a symlinked path component (to a protected
  tree or anywhere else); a non-local filesystem (`/proc/mounts`, 9p
  injected in the test); a symlink entry in the fold dir; a hard-linked file
  (nlink > 1); no sentinel; a sentinel copied from another dir; a reused fold
  number. A further test checks that the DEFAULT config protects the real
  repo `data/` and the stage dir by comparing path values only (nothing is
  stat-ed or created there).
- **Manifest repoint** (`compose_fold_manifest`): writes a NEW composed
  manifest under `<fold_root>/manifests/`. Shard s's record names the fold's
  dv-v2 dir, with `fold_origin: "fold:s:k"` and `fold_of` (the original
  record). Every other record is copied verbatim. The function never
  overwrites a file and never touches the base manifest; the tests compare
  bytes before and after.
- **Operator publish**: `cli.py publish-fold --shard s --fold k [--confirm]`.
  Without `--confirm` it is a dry run that reports the plan and writes
  nothing. The fold must be `ready` (`mark_fold_ready` attaches the F2/F3
  evidence; `build_fold` only reaches `built`). On confirm: baseline
  snapshot → guard → composed manifest → ledger update (`seismic_origin` for
  members whose `last_seen` equals the snapshot) → `generation.publish` with
  the composed manifest as base → baseline check. `generation.publish` then
  keeps using the newest published fold manifest as its base when no
  `--base-shard-manifest` is given. It composes a delta `shard_manifest.json`
  whenever a base record carries `fold_origin`, even with no delta SEISMIC
  shard. With no published fold both are as before.
- **Baseline** (`baseline_snapshot` / `baseline_check`): size + mtime_ns of
  every file under `data/seismic_150m`, `data/thinclient_index`,
  `/var/tmp/seismic_stage`, taken before and after `build_fold` and
  `publish_fold`. CHANGED or new raises at once. MISSING (9p stat transient)
  is re-checked 5 × 24 s first. The ignore list is the closed in-place
  bench's (`meta.sqlite-wal/-shm`, `staged_manifest.json`, `.staged_ok`).
  The tests show that a change, a new file and a missing file each abort,
  including a change made during `publish_fold`. Limit: the check runs after
  the publish, so a difference aborts the run and reports it but cannot undo
  the publish.
- **Pinned token map** (G1 consequence): `build_fold` refuses to run without
  `token_map_dir`. The build gets `input_token_to_id_map` = that dir's
  `token_to_id_map.bin`. Tokens of folded delta docs that the map lacks are
  appended at max+1… in sorted order; the fork would otherwise panic on
  `token_to_id_mapping[&t]` (`inverted_index_wrapper.rs` `process_data`).
  Toy end-to-end (`test_foldin_e2e.py`, real SEISMIC build of 300 docs):
  every base token keeps its id, the new token is appended and served, and
  the fold's doc mapping is (base − updated − deleted) + the 2 folded docs.
  **At full scale, the effect of appended tokens on parity is UNMEASURED.**

## G4 — per-leg newest-origin masks (commit 11527c59)

- `shard_origins` returns `"fold:s:k"` for a composed-manifest record with
  `fold_origin`. `None` (base) and `int` (delta generation) are unchanged.
- `generations.json` `mask.newest_by_leg.seismic = {id: "fold:s:k"}` is
  written by `IngestLedger.mask()` only when a live doc's `seismic_origin`
  is set. `superseded` stays the sections/meta/abstract leg's newest
  generation.
- Per-shard SEISMIC filter on delta and fold positions:
  `seismic_newest.get(id, superseded.get(id, origin)) == origin`. A set
  livedocs bit drops a doc there only when it is in neither map, i.e.
  deleted. Base positions are unchanged. BM25F / `filter_ids` / `meta_rows`
  / `abstract_owner` do not read the new map.
- `attach_seismic` also installs the filter without a livedocs bitset when a
  fold is served. Otherwise a folded doc would be served from s′ AND from
  its delta generation.
- Ledger writer rule: `seismic_origin` is set only by `publish-fold`, and
  every re-stage resets it to NULL.
- Tests (`test_foldin_masks.py`): every (leg × origin) case for 9 doc states
  (untouched base in s′; untouched base in another shard; updated-then-folded;
  new-then-folded; folded-then-re-updated; folded-then-deleted, base and new;
  updated in another shard, not folded; re-staged into the buffer) across
  SEISMIC base / fold / gen 1 / gen 2 positions, BM25F base / gen / buffer,
  SPLADE post-merge, meta and abstract owner; "each live doc is served from
  exactly one SEISMIC origin". No fold: the filter equals the pre-G4 body
  (copied into the test) on 2,000 / 2,000 random cases, and `shard_origins`
  / `attach_seismic` / `filter_ids` are unchanged. Invariants:
  `docs/CODE_INVARIANTS.md` §"Fold-in per-leg newest origins".
- **M1 gate-off parity 120/120 on 2 passes after the change: NOT RUN by this
  agent** (the brief assigns M1 to agent SERVE's P3 on the lever code). The
  G4 change landed in **11527c59** (2026-10-01 ~17:00Z). SERVE's P3 covers
  it only if P3's code snapshot commit is 11527c59 or a descendant (`git
  merge-base --is-ancestor 11527c59 <P3 commit>`). Otherwise run:

```
cd /workspaces/sfu-library-thinclient
SFU_SPLADE_MODEL_PATH=/home/vscode/work/models_local/splade_onnx_fused \
SFU_CE_MODEL_PATH=/home/vscode/work/models_local/sfu-cross-encoder-v1 \
SFU_EMBEDDING_MODEL_PATH=/home/vscode/work/delta_ingest/m1/models/sfu-academic-embed-v5 \
SFU_SEISMIC_STAGE_DIR="" SFU_META_STAGE_DIR="" \
nice -n 10 .venv/bin/python3 scripts/experiments/eval_delta_ingest_m1_2pass.py drive \
  --passes 2 --arms gate_off,empty_root --commit $(git rev-parse HEAD) \
  --python /home/vscode/work/venv_local/bin/python3 --parallel --lock-shared \
  --cpus gate_off=0-3,empty_root=4-7
```

  (shared lock, ~1 h *est.* from the 2026-10-01 M1 run; bar 120/120 fused +
  final top-10 identical on each of 2 passes, `03_SPIKE_PLAN.md` row M1.)

## G6 — encoder calibration (recorded, not gated): PARTIAL

- From O14 (`data/eval_results/delta_ingest_O14_base_reuse_20261001.json`
  key `gpu_check`, commit 56d38a39, 2026-10-01 06:10Z, 1,882 text-unchanged
  base docs of shard 0 / `social_sciences__recent`, TRT encoder):
  **mean nnz re-encoded 83.18 vs stored 83.00** (ratio 1.0022), cosine mean
  0.99998 (p1 0.99996), term Jaccard 0.9935, 0 docs bit-identical.
- **The L2 norm is not in that file, and no re-encoded vectors were saved**
  (checked 22:18Z: O14 wrote only aggregates). So the L2 half of G6 needs
  a GPU re-run. `g6-calib` in the same harness repeats the O14 selection
  exactly and records nnz, L2 (ratio of means, per-doc ratio p1/p50/p99 and a
  bootstrap CI) and L1. It is queued as step 2 of `fold_queue.sh`
  (*est.* < 5 min, encode ~4 s plus model load and a meta scan).
- Reading (inference, not measured): cosine 0.99998 with nnz +0.2% bounds a
  direction shift but not a scale shift, and a scale shift is what G6 asks
  about. The L2 ratio is the open number.

## What changes a premise in the track docs

- **Folded docs are masked in the delta SEISMIC shards, not removed.** Doc
  10 §0 says the fold drops "the folded docs from the delta layer". This
  code serves them from s′ only (G4 filter). Their vectors stay in the delta
  generations' SEISMIC shards until a compaction rebuilds those shards, and
  `compact()` today re-includes every live record's vector, folded or not.
  No compaction rule excludes `seismic_origin IS NOT NULL` docs; it is not
  built. F3's F arm should be built with the folded docs out of the delta
  SEISMIC leg (doc 10 §6 F3 already specifies "s′ + consolidated sections
  tier", i.e. `seismic=False`).
- `route_shard` exists only in ledgers created at or after 58970753 and in
  ledgers migrated with `cli.py backfill-routes`. The existing M4/M2/M3
  roots are NOT migrated (by design; their copies were).
- Appending unseen tokens to the pinned map works at toy scale only.

## First fold measurement (F-bars): exact order, NOT RUN

Prerequisites: G1 (holds), the G2 bar (queued), G3/G4 code (this file), M1
after 11527c59, G6 L2 (queued; must be recorded before F2). The F2 harness `scripts/experiments/eval_delta_ingest_foldin.py`
was **written 2026-10-03** (subcommands `encode`, `build`, `preview`,
`measure`, `summarize`, `run`; doc 10 §6 is copied verbatim into its header,
checked by `scripts/tests/test_foldin_f2_harness.py`, 10 tests on synthetic
rows and tmp trees). **IMPLEMENTED, NOT RUN: no fold is built, no index was
loaded by it, F2 and F4 are UNMEASURED.** It covers F2 and the F4 build
record only; F1, F3, F5, F6 and F8 have no harness. Its header fixes five
implementation readings of the frozen F2 row before the first run (what
"shard 0's own results" means; Q-a read on the federated leg with the
shard-own overlap recorded; the Q-b reference recomputed from the drift
run's saved R and A0 outputs; Q-c on the final top-10; what counts as a Q-d
leak). The F arm is a preview root (the fixture's `generations.json` plus
the composed fold manifest and the `newest_by_leg.seismic` map that
`publish-fold` would write), so F2 runs before anything is published.
Without `--bar-reading A|B` the F2 verdict is NOT READ (owner question
below). On the `root_n8` fixture Q-d is weak: the ledger has 0 tombstones
and 0 superseded docs, so only double-serving of folded docs is exercised.

1. Fixture copy (lock-free, ~2 min *est.*, 1.5 GB): copy the M4 corpus (b)
   root `root_n8` (8 generations, 160,347 docs, 20,112 routed to shard 0 by
   the backfill-on-copy above) to the fold workspace and migrate the copy:
   ```
   cp -a /home/vscode/work/inplace_update/m4/root_n8 /home/vscode/work/delta_ingest/foldin/fixture_n8
   .venv/bin/python3 -m spike.delta_ingest.cli backfill-routes \
     --delta-root /home/vscode/work/delta_ingest/foldin/fixture_n8 --profile desktop_gpu
   .venv/bin/python3 -m spike.delta_ingest.cli publish \
     --delta-root /home/vscode/work/delta_ingest/foldin/fixture_n8 --profile desktop_gpu
   ```
   The `publish` rewrites the copy's `generations.json` with the copy's own
   generation paths. Arm L = A0 + this root.
2. Fold build of shard 0 (EXCLUSIVE lock: peak *est.* 9.6–10.1 GB from the
   drift build/c1a/dotvbyte; wall *est.* 35–45 min = dump ~4 min at 8
   workers + build 1,400–1,900 s + c1a 60–365 s + dotvbyte 130–195 s;
   scratch *est.* 39 GB jsonl + 8.3 GB stock, deleted after;
   output *est.* 7.8 GB f16 + 5.5 GB dv-v2; free disk 593 GB at 17:05Z):
   ```
   touch /tmp/sfu_wave3/EXCL_WAITING_<AGENT>
   SFU_SEISMIC_STAGE_DIR="" SFU_META_STAGE_DIR="" SFU_DELTA_ROOT="" \
   flock -x /tmp/sfu_latency_measure.lock nice -n 5 taskset -c 0-15 \
     env OMP_NUM_THREADS=8 RAYON_NUM_THREADS=8 timeout 3h \
     /home/vscode/work/venv_local/bin/python3 -m spike.delta_ingest.cli fold-build \
       --delta-root /home/vscode/work/delta_ingest/foldin/fixture_n8 --shard 0 \
       --fold-input /home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap \
       --token-map-dir /home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap \
       --fold-root /home/vscode/work/delta_ingest/foldin --fold-workers 8 \
       --profile desktop_gpu --seismic-threads 8
   rm /tmp/sfu_wave3/EXCL_WAITING_<AGENT>
   ```
   F4 (wall per stage, peak RSS incl. VmSwap, scratch and output bytes) is
   recorded from this run only on a quiet host. `build_fold` records
   stage seconds but not peak RSS; the harness's `build` subcommand
   (2026-10-03) runs the same `fold-build` as a child under the exclusive
   lock and adds the process-tree VmRSS + VmSwap peak, the peak and final
   fold-dir bytes and the output-size bar (results key `F4_build`; the
   publish stage is not in it):
   ```
   /home/vscode/work/venv_local/bin/python3 scripts/experiments/eval_delta_ingest_foldin.py build \
     --fold-input /home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap \
     --token-map-dir /home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap
   ```
3. F2 parity (shared lock OK, ~30 min *est.*): F (federated manifest with
   s′ at position 0 + masks) vs L, QT/QD/QA, bars Q-a…Q-d as frozen:
   ```
   P=/home/vscode/work/venv_local/bin/python3; H=scripts/experiments/eval_delta_ingest_foldin.py
   $P $H encode && $P $H preview && $P $H run --bar-reading <A|B>
   ```
4. F1 (no lock, ~15 min): trigger bookkeeping vs brute force on the fixture
   and on a COPY of `root_n8` (`IngestLedger.routed_live_counts()` is the (a)
   numerator; the (d)/(c) counters are not written).
5. `mark_fold_ready` with the F2 evidence, then `publish-fold --confirm` on
   the fixture root only (never on a served root), then F3 / F8 (exclusive)
   and F5 (fixture builder not written).

## Open question for the owner (raised by DRIFT; not decided here)

Doc 10 F2 Q-a sets the per-set bar `bar_set` two ways:

- **Reading A, G1 NOISE branch** (the branch G1 selected): `bar_set =
  min(0.99, m_set) − 0.005` = **0.985** (QT) / **0.980** (QD). This allows
  for the unpinned build-vs-build drift DRIFT measured (0.9908 / 0.985). It
  is the branch the frozen G1 table selects for the NOISE outcome.
- **Reading B, "under a G1 remedy: 0.99"**: the fold pins the token-id map,
  i.e. remedy R-a. DRIFT measured that this rebuild reproduces the served
  shard at 1.000 / 1.000 (220/220 top-10). So the noise the NOISE branch
  allows for is absent from the procedure the fold actually uses, and 0.99
  would be the bar. Doc 10 attaches that branch to the REAL LOSS / MIXED
  outcomes, which did not occur.

Facts that bear on it: the fold is not a no-op rebuild. s′ drops masked base
docs and adds delta docs, so F vs L also differs by legitimate ranking
changes. Those are bounded by Q-b (vs R/A0) and Q-d (mask leak). The
appended-token path is unmeasured at scale. Doc 10's "stricter consequence
governs" clause covers disagreements between item N's verdict and the G1
table; whether it covers this choice is not stated. The owner should record
the choice in a dated addendum to doc 10 BEFORE F2 runs.
