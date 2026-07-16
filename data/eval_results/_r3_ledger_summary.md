# R3 kernel-ledger — per-cell summary (2026-07-16)

Cell-by-cell log for the R3 kernel-ledger spike (doc
`docs/seismic_150m_testbed/15_R3_KERNEL_LEDGER_SPIKE.md`; pre-registered bars
in `11_EXPERIMENT_BACKLOG.md` §R3). Each row is appended ONLY after the cell
passes the full R2 checklist + R3 ledger checks (`r3_verify_cell.py`,
VERDICT VALID / UNCONVERGED / INVALID). Latency is quoted ONLY from control
cells (doc 15 §4); instrumented cells contribute residency/attribution state.

Cell plan (doc 15 §5): 16g-ctrl, 12g-ctrl, 16g-instr, 12g-instr — the R2
12/16 GB inversion pair, each with an uninstrumented control + an
instrumented (bpftrace ledger+refault tracer) cell.

## Per-cell table

| label | cap | mode | converged | passes | pass1 majflt | pass3 p50 ms | final p50 ms | final majflt | ms/flt | swap | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cap16g_ctrl | 16g | ctrl | near_zero | 5 | 103833 | 129.28 | 33.76 | 1864 | 0.749 | 0 | VALID |
| cap12g_ctrl | 12g | ctrl | near_zero | 4 | 243600 | 20.26 | 18.31 | 2 | 0.36 | 0 | VALID |
| cap16g_instr_r3fix | 16g | instr | near_zero | 5 | 103917 | 138.61 | 37.82 | 2122 | 0.43–0.72 | 0 | INVALID (overhead 1.12×; ledger+refault clean — see §) |
| cap12g_instr_r3fix | 12g | instr | near_zero | 4 | 244082 | 20.53 | 18.92 | 1008 | 0.37–1.09 | 0 | INVALID (SUPERSEDED by r3h — ledger drop 11.8%) |
| cap12g_instr_r3h | 12g | instr | near_zero | 5 | 242525 | 824.33¹ | 18.42 | 17 | 0.34–1.09 | 0 | **VALID** (the clean instr cell) |

¹ 12g r3h's pass-3 p50 is 824 ms (mid-sort, majflt 139954) because the tracer's
between-pass cachestat-snapshot pressure *delayed 12g's convergence to 5 passes*
(vs ctrl's 4). This is the observer-effect doc 15 §4 warns about; the
overhead bar is therefore compared at each cell's *steady-state* pass (min
majflt), not a fixed index — see the verifier + per-cell sections. Latency is
NOT quoted from any instr cell; the controls above carry it.

The instrumented cells span two probe generations: `r3fix` = REQ-3g (corrected
probes, but the ledger STILL contained the 3 vmscan batch-context tracepoints
→ 12g drop 11.8%); `r3h` = REQ-3h (vmscan tracepoints DROPPED, the fix). The
12g r3h cell SUPERSEDES the dropped 12g r3fix cell (drop=0, VALID). The 16g
r3fix cell is retained (its 16g ledger was drop-clean — 16g doesn't
reclaim-storm — and feeds the join's 16g-side attribution; its overhead
1.120× is the one failing check).

## cap16g_ctrl — VALID (control; latency-quotable)

Result `r3_cap16g_ctrl_20260715.json`; log `_r3_cap16g_ctrl_drive.log`; status
`_r3_cap16g_ctrl.status`. Driver `r3_kernel_ledger_driver.py`, 40 pre-encoded
queries, top-50, prefault-ON, traversal-only latencies. Reproduces R2's 16g cell
within noise: pass majflt 103833→56144→14782→5164→1864 across 5 passes, converged
near_zero at pass 5. Pass-3 fixed-window p50 = 129 ms (R2 measured 135 ms;
the transient inversion value). Final p50 33.76 ms at majflt≈1.9k (the R2
note's residual-fault tail inflating the final pass — steady-state quote
would be the pass-3 129 ms under pressure, here convergence is the story).
All R2 checklist checks PASS: swap_confounded=false, near_zero kind,
pass-1 majflt 103k≥50k, ms/fault 0.40–0.75 in [0.1,2.0], p50≥15, cg_delta
active. R3 ledger checks N/A (control). Pass-boundary CLOCK_MONOTONIC ns
recorded (6 marks: 1 post-load + 5 pass-ends) for the instr-cell ledger
slicing. load_s 231.7 (cold fill + prefault).


## cap12g_ctrl — VALID (control; latency-quotable) — THE INVERSION REPRODUCED

Result `r3_cap12g_ctrl_20260715.json`; log `_r3_cap12g_ctrl_drive.log`; status
`_r3_cap12g_ctrl.status`. Reproduces R2's 12g cell: converged near_zero in 4
passes (majflt 243600→182965→26770→2), **pass-3 fixed-window p50 = 20.26 ms**
(R2: 21 ms) vs 16g_ctrl's 129 ms — **the 12g-beats-16g inversion reproduced
cleanly** (smaller cap finishes the sort under the fixed window while 16g is
still thrashing). Final p50 18 ms. All R2 checks PASS (swap 0, near_zero,
pass-1 majflt 243k≥50k, ms/fault 0.35–0.37 in range, p50≥15, cg_delta
active). R3 ledger N/A (control). load_s 180.9.

## R3 instrumented-cell tracer defect found (16g_instr breadcrumb guard fired)

The orchestrator's 90s breadcrumb guard caught a real bpftrace field-name defect
in seconds (not 1h) — the design working as intended. Two errors in the
prior-session probe syntax (same silent-zero-event class as the REQ-1
`--include` defect I fixed in 87be87a, but distinct field-name bugs):

1. **`args->ino` is not a field** on `filemap:mm_filemap_add_to_page_cache` /
   `_delete_from_page_cache`. The kernel (6.x `include/trace/events/filemap.h`
   `mm_filemap_op_page_cache` event class) exposes the inode as **`args->i_ino`**
   (`__field(u64, i_ino)`; `TP_fast_assign __entry->i_ino =
   folio->mapping->host->i_ino`). `args->index` (page offset) IS correct. Fix:
   `args->ino` → `args->i_ino` throughout `r3_ledger.bt`. The DEL probe gains
   a real pgoff too (the tracepoint DOES carry `index` — the prior session's
   "delete carries ino but NOT pgoff" note was based on the wrong struct; the
   event class has `index` for both add and delete).
2. **`arg0` is invalid for `kfunc`** (bpftrace: "The arg0 builtin can only be
   used with kprobes, uprobes and usdt"). The refault probe's kfunc handler
   used `$folio = (struct folio *)arg0;`. kfunc accesses args via the named
   BTF fields, not `arg0`. Fix: use `args` (the kfunc's typed arg tuple) —
   workingset_refault's first arg IS the folio in modern bpftrace, accessed
   differently. See r3_refault_probe.bt fix.

Both control cells (16g, 12g) are DONE + VALID and reproduce R2 incl. the
inversion. The two instrumented cells (16g_instr running, 12g_instr pending)
have DEAD tracers (both probes failed to attach → empty ledger/refault). The
cells themselves will complete (driver unaffected), but their ledgers will be
INVALID by Phase C. Fix committed; REQ-3 will re-run both instr cells with the
corrected probes.

## cap16g_instr — PARTIAL (cell + cachestat maps VALID; ledger/refault INVALID — pre-fix probes)

Result `r3_cap16g_instr_20260715.json`; status `_r3_cap16g_instr.status`;
cachestat maps `_r3_cachestat_cap16g_instr_pass0..4.json` (5 snapshots, ~3.3MB each);
ledger `_r3_cap16g_instr_ledger.log` + refault `_r3_cap16g_instr_refault.log` — **EMPTY
(probes failed to attach with the pre-fix field names, recorded below)**.

Cell driver: VALID (R2 checks pass — swap 0, near_zero in 4 passes, pass-1 majflt 103850≥50k,
ms/fault 0.42, final p50 19.47 ms, cg_delta active; reproduces 16g_ctrl within noise:
majflt 103850→58205→10561→0). `--cachestat-between-passes` ON → 5 residue maps snapped
(load + 4 pass boundaries). **Instrument 4 (cachestat) WORKED** — the between-pass residency
half of expectation #3 IS measured (RESIDUE MAPS AVAILABLE for Phase D, below).

R3 ledger checks: **INVALID** (empty ledger — `refault_within_2x_majflt` fails: 0 refaults /
~172k majflt = ratio 0; `ledger_drop_rate` spuriously "ok" because no events at all). The
verifier's Phase-C safety net caught the empty-ledger at the refault-ratio check (working as
designed). Latency NOT quoted (instr cell, per §4 — latency comes from 16g_ctrl).

**Defect (FIXED in 7aa2590, REQ-3 re-runs both instr cells):** the pre-fix probes failed:
`args->ino` is not a field on the filemap tracepoints (correct: `args->i_ino`), and `arg0` is
invalid for kfunc (correct: `args.folio` dot-syntax). The 90s breadcrumb guard fired on both
instr cells — the guard working as intended (caught a real attach failure in seconds, not 1h).
The cachestat maps from this cell ARE retained and feed Phase D expectation #3; the
ledger/refault attribution halves (expectations #1, #2) need the REQ-3 re-run.

## cap12g_instr — PARTIAL (cell + cachestat maps VALID; ledger/refault INVALID pre-fix)

Result `r3_cap12g_instr_20260715.json`; status `_r3_cap12g_instr.status`; cachestat maps
`_r3_cachestat_cap12g_instr_pass0..4.json` (5); ledger/refault EMPTY (pre-fix probe errors).

Cell driver: VALID (R2 checks pass — swap 0, near_zero 4 passes, pass-1 majflt 277875≥50k,
ms/fault 0.365, final p50 18.77, cg_delta active). `--cachestat-between-passes` ON → 5 maps.
**Instrument 4 (cachestat) WORKED** → expectation #3 residue maps available.

R3 ledger INVALID (empty, pre-fix probes — same defect as 16g_instr). Observer-effect check:
12g_instr final p50 18.77 / 12g_ctrl 18.31 = **1.025× ≤ 1.10× — the cell-side observer-effect
bar PASSES** (the bpftrace probes were dead, so added zero tracing overhead; the only pressure
delta is cachestat-between-passes + the tracer container's footprint). NOTE: pass-3 majflt
121,666 vs 12g_ctrl's 26,770 — the instr cell faults ~4.5× MORE at pass 3 (the cachestat
snapshots + tracer container added memory pressure, aging the active list faster); this is
the kind of reclaim-timing perturbation doc 15 §4 warns about, and why latency is quoted only
from controls. Latency NOT quoted.

**FIXED in 7aa2590; REQ-3 re-runs both instr cells (16+12) with the corrected probes** for the
ledger × refault attribution half (expectations #1, #2). The cachestat maps from both instr
cells feed expectation #3 regardless of the re-run.

## REQ-3 REJECTED → REQ-3b: the third bpftrace load defect (BEGIN merge assumption)

The host monitor REJECTED REQ-3 before running it (caught via its own bpftrace
dry-compile): "More than one BEGIN probe defined" — this bpftrace version does
**NOT** merge multiple BEGIN blocks (my 87be87a concat design assumed it does,
per the docs; the deployed version rejects it). Concatenating `_r3_inode_set.bt`
(its own BEGIN) + `r3_ledger.bt` (breadcrumb BEGIN) = 2 BEGINs → compile error →
zero events (same silent-failure class as the `--include` defect).

**FIX (commit pending):** the inode filter is now a **BODY fragment**
(`_r3_inode_body.bt` — the `@shard_inodes[]=` + count lines, NO BEGIN wrapper),
spliced INTO each probe's SINGLE BEGIN at a `/*INODE_BODY*/` placeholder via
`sed -e '/\/\*INODE_BODY\*\//r <body>' -e '/\/\*INODE_BODY\*\//d'`. Exactly ONE
BEGIN per probe, body populated inside it, breadcrumb reads `@shard_inodes_count`.
Verified locally: spliced ledger + refault each have count(BEGIN)=1 with the 8
inodes + count inside. Also: readiness-wait budget 90s→150s (apt-get alone ate
~60s both REQ-2 cells, monitor noted) + a TRACER_FAIL branch that surfaces a
bpftrace compile ERROR immediately (so a failed splice is caught in seconds,
not after a cell). Resubmitted as REQ-3b.

## REQ-3b REJECTED → REQ-3c FAILED-STOPPED: the fourth load-path defect (bash-c nesting)

The single-BEGIN body-fragment splice (f533c18) fixed the BEGIN-merge, but the
orchestrator's runtime `sed -e "/.../r body" -e "/.../d"` lived inside
`start_tracer`'s `bash -c "..."` **double-quoted** string. REQ-3b was REJECTED
(monitor dry-compile): the sed `r` expression had a one-char typo `\*\*/r`
(star-star, matches nothing) → body uninjected → `shard_inodes_loaded=0`.
ccce930 fixed that to `\*\//r` — but REQ-3c then FAILED-STOPPED: even the
corrected sed, inside the double-quoted `bash -c "..."`, has its own double
quotes terminate that string early. Host evidence:
`r3_host_orchestrator.sh: line 94: r: command not found` + `d: command not
found` — the host shell executed the sed fragments as bare commands; the
tracer container received a truncated script; the 150s breadcrumb WARN fired →
empty ledgers. The 16g_instr_r3fix cell died rc=137 as a SYMPTOM (the
un-instrumented driver ran under the 16g cap with no tracer). Monitor + drive
session diagnosed the quoting nesting independently.

**FIX (commit a2ef6ab, REQ-3d):** do the splice ON THE ORCHESTRATOR SIDE, in
normal Python (`scripts/seismic_testbed/r3_splice_probes.py`), into COMMITTED
files `r3_ledger_spliced.bt` / `r3_refault_probe_spliced.bt`. The tracer's now
SINGLE-quoted `bash -c '...'` body just `bpftrace <file>`s them — NO sed, NO
nested quotes, NO MSYS backslash mangling. This is the 4th attempt at this one
code path (--include → BEGIN-merge → sed-typo → bash-c-nesting); pre-splicing
eliminates the whole nesting class. The generator machine-verifies BEGIN=1 +
splice-point-gone + count-line-present before writing; `bash -n` on the
orchestrator AND on the assembled bash-c body both PASS. f533c18 single-BEGIN +
7aa2590 field fixes (args->i_ino; fentry: args.folio) retained. REQ-3d submitted.

## Expectation #3 ("the sort, pictured") — CONFIRMED from REQ-2 cachestat maps

**MEASURED 2026-07-16 (partial: cachestat half, from REQ-2 PARTIAL instr cells).**
Instrument 4 (`r3_cachestat_map.py`, syscall 451) WORKED in the REQ-2 instr
cells even though the ledger/refault probes (instruments 1+3) were dead
pre-fix. The between-pass residency maps directly picture the 04-doc §2.2
mechanism at page-cache granularity — the finer view R3 promised over R2's
cgroup aggregates. `_r3_cachestat_cap{12,16}g_instr_pass0..4.json` (5 maps each):

| pass | 12g cache GB | 12g evicted GB | 16g cache GB | 16g evicted GB | reading |
|---|---|---|---|---|---|
| 0 (post-load) | 11.363 | **3.164** | 14.528 | **0.000** | 16g holds the FULL ~14.3GB working set; 12g already pressure-sorting |
| 1 | 9.366 | 1.615 | 13.403 | 2.361 | 16g only STARTS evicting at pass 1 (lazy reclaim, light pressure) |
| 2 | 9.862 | 1.660 | 12.687 | 2.389 | both shedding residue |
| 3 | 10.327 | 1.202 | 10.926 | 0.000 | 16g drives to evicted=0 (repeat set resident) |
| 4 | 10.329 | 1.201 | 10.926 | 0.000 | both converged; cache ≈ 10-11 GB repeat set |

**Verdict on expectation #3: CONFIRMED.** As pre-registered: at pass 0 (post-load)
16g holds the full load residue (evicted **0.0 GB** = working set fits, kernel
not yet sorting) while 12g is already shedding (evicted **3.16 GB** = pressure
hot, sort in flight) — the "16g not yet sorting / 12g sorting" asymmetry of
04-doc §2.2 pictured residually. Both drain to the ~10-11 GB repeat set
(04-doc §2.1) by convergence (final cache 12g 10.33 / 16g 10.93). The
running `r3_join_analysis.py` reproduces this verdict from the same maps
(pass0 evicted 12g=3.16/16g=0.0; final cache both ≤11.2 → CONFIRMED).

**Caveat (recorded honestly):** this is from the REQ-2 *instr* cells, where the
tracer + cachestat snapshots added pressure that **accelerated 16g's sort** —
the 16g_instr cell converged in 4 passes (not 5 like its uninstrumented control);
its pass-3 cachestat already shows evicted=0 (control 16g was still mid-sort at
pass 3, 14.8k faults). This is exactly the observer-effect-on-reclaim-timing
doc 15 §4 warns about, and it is WHY latency is only quoted from control cells.
So the literal pre-registration ("16g still holding residue at pass 3") is
true of the **control** 16g (still 129 ms / 15k faults at pass 3) but NOT of
the instr 16g (cachestat perturbed it to converge sooner). The mechanism
pictured — 16g lags 12g's sort — holds in both; the timing of "pass 3" shifts
under instrumentation. Recorded, not massaged.

## Pending REQ-3d (instrumented-cell ledger/refault attribution)

Expectations #1 (attribution: 12g residual faults concentrate in slow-tail
query extents), #2 (refault decision site), and #4's drop-rate half depend on
the ledger × refault join, which needs the corrected probes to ATTACH — the
REQ-3d re-run. The query-extent map (instrument 5) is READY (40 queries,
10471 distinct 2 MiB extents — its sharing profile: 2050 extents touch all 40
queries, only 191 touch a single query → the join concentration signal for #1
is whether pass-3 faults land in that rare single-query left tail). Controls
(12g/16g, latency-quotable) are DONE + VALID from REQ-2; the inversion
reproduces (12g pass-3 p50 20.26 ms vs 16g 129.28 ms). REQ-3d outcome TBD on the
host monitor (hourly). Residual uncertainty: whether WSL2 6.18.33 BTF resolves
`args.folio.mapping.host.i_ino` end-to-end (struct folio `mapping` is a union).

## REQ-3g DONE-PARTIAL (2026-07-16) — both instr cells RAN; both probes ATTACHED

The corrected-probe stack (spliced single-BEGIN + `args->i_ino` field fix +
kprobe `workingset_refault` with BTF walk `$folio->mapping->host->i_ino` /
`$folio->index`) attached and streamed on the host. Predictor confirmed: the
BTF field walk DID resolve — refault event lines carry real non-zero shard
inodes (all 8, distinct counts 120–610) and extent-aligned pgoffs (`% 512 ==
0` verified). The 1/512 extent downsample (the REQ-3f perf-ring fix) held:
ledger 16g lost=0, refault 16g lost=0. So both probes are LIVE and correctly
filtered. The cells themselves converge near-zero reproducing their controls.

But `r3_verify_cell.py` returns **INVALID for BOTH** instr cells, each for a
DISTINCT reason. Per F6 (a number failing a check is recorded INVALID, never
quoted as a result), neither is banked as VALID; the cause and what is
salvageable is recorded below.

## cap16g_instr_r3fix — INVALID ONLY on overhead (1.12× steady-state); ledger + refault CLEAN

Result `r3_cap16g_instr_r3fix_20260715.json`; ledger `_r3_cap16g_instr_r3fix_ledger.log`
(175k lines, drop=0 verified — no "Lost N events" line, ADD 9790 / DEL 3341 on
the 8 shard inodes, all inodes ⊆ inode map); refault `_r3_cap16g_instr_r3fix_refault.log`
(2476 events, BTF walk resolved, lost=0); cachestat `_r3_cachestat_cap16g_instr_r3fix_pass0..5.json`.

Cell behavior reproduces 16g_ctrl within noise: majflt 103917→56126→14740→5177→2122
(ctrl 103833→56144→14782→5164→1864) — total faults +0.85%. Per-pass p50 overhead
vs control: pass1 1.107×, pass2 1.065×, **pass3 1.072×**, pass4 1.082×, pass5 1.120×.
The 1.120× (over the 1.10× bar) is ONLY the final pass — the residual-fault tail
(2122 vs 1864 faults, the artifact §5.1 "tiny denominator" regime). Passes 2–4
(the stable faulting regime) are within the 1.10× bar.

Two verifier checks FAIL, hence INVALID:

1. `refault_within_2x_majflt` = **6.96** (2476 sampled refaults × 512 ≈ 1.27M vs
   182k majflt). This is NOT a broken filter — the refault probe's inodes/pgoffs
   are verified-real and drop=0. It is a **verifier-heuristic limitation**: the
   bar assumes sampled_refault×512 ≈ majflt within 2×, but `workingset_refault`
   fires per *page* that finds a shadow entry while `majflt` counts coalesced
   readahead-I/O servicing events — a systematic ~3–9× over-count is expected
   across all passes (measured per-pass-window ratio 2.4–5.5×, stable, NOT a
   gross 0×/1000× mismatch a broken filter would show). The heuristic's 2× band
   is too tight for a readahead-coalescing kernel; the probe is sound. Recorded
   as the cause, NOT massaged into a pass (F6); the ledger/refault data is
   join-usable for the 16g-side of expectation #1's attribution join.
2. `instr_overhead_le_1.10x` = **1.120×** (final-pass residual-fault tail only;
   pass-3 is 1.072×). The instability is exactly the residual-fault-tail regime
   artifact §5.1 says is not a steady-state quote — recorded, not averaged away.

**Salvaged:** the 16g ledger is drop-clean and correctly filtered → it IS valid
input for expectation #1's 16g-side attribution (the 16g half of the 12g-vs-16g
comparison the prediction needs). With a clean 12g ledger (REQ-3h, below), the
join can verdict #1 on valid inputs.

## cap12g_instr_r3fix — INVALID (ledger drop 11.8% — the vmscan batch-context firehose)

Result `r3_cap12g_instr_r3fix_20260715.json`; ledger `_r3_cap12g_instr_r3fix_ledger.log`
(465k lines, **lost=62145 → drop_rate 0.1179** — OVER the §R3 ≤1% bar by
construction); refault `_r3_cap12g_instr_r3fix_refault.log` (7772 events, lost=0,
BTF walk resolved); cachestat `_r3_cachestat_cap12g_instr_r3fix_pass0..4.json`.

Cell behavior reproduces 12g_ctrl within noise: majflt 244082→183081→26772→1008
(ctrl 243600→182965→26770→2). Per-pass p50 overhead vs control: pass1 1.038×,
pass2 1.073×, **pass3 1.013×**, pass4 1.033× — **the observer-effect bar PASSES
at 12g** (every pass within 1.10×). The 12g refault-ratio heuristic also fails
(8.75, same ~×512-counting-model gap as 16g, not a filter break — refault inodes
verified-real, lost=0).

The single INVALID cause is **the ledger drop rate (11.8%)**, and the mechanism
is now fully isolated (the monitor's composition, verified against the log):
the `% 512` downsample gates ONLY the ADD/DEL page events (which have `index`).
The three vmscan batch-context tracepoints (`RBEG`/`REND`/`SHRINK`) carry NO
page index → cannot be downsampled → fire per-batch-event at 12g (the
reclaim-storm cap). 12g ledger composition: 138,943 RBEG + 138,850 REND +
164,280 SHRINK (= 442k, **95%** of events) vs only 13,606 ADD + 9,291 DEL. The
batch-context firehose overran the perf ring; the ~23k page events (the join's
actual attribution input, correctly inoded) are a tiny minority swamped by
context. The join only keys on ADD/DEL, so RBEG/REND/SHRINK contribute NOTHING
to attribution — they are pure buffer pressure with no join value.

**Salvaged:** the 12g refault log (lost=0) and the 12g cachestat maps are clean
(the drop is ONLY in the ledger's vmscan events). But the §R3 discard rule
(drop>1% → ledger INVALID, latency never) applies: this 12g ledger is INVALID
as a whole and must NOT be quoted for expectation #1 (the load-bearing
inversion-attribution comparison needs 12g-vs-16g on a clean 12g).

**Fix (REQ-3h, below):** drop the three vmscan batch-context tracepoints from
the ledger probe entirely. The driver's per-pass cgroup `pgscan`/`pgsteal`
deltas already carry the same reclaim-pressure signal at pass granularity
(in `cg_delta`), and the join never keys on RBEG/REND/SHRINK. Removing them
cuts volume ~21× (442k→~23k on 12g) → drop→~0%, the ADD/DEL attribution stream
preserved unchanged. Pre-authorized by doc 15 §4 ("downsample and rerun" —
here, the downsample is dropping the non-attributable context events). Resubmit
REQ-3h for the 12g instr cell ONLY (16g instr stays banked-salvageable; do NOT
clobber its files — the suffix isolates the re-run).


## REQ-3h DONE (2026-07-16T06:53Z) — the clean 12g instr cell banked VALID

The vmscan-dropped ledger probe (commit f9ffa04) ran the 12g instr cell
(`_R3_DATE_SUFFIX=r3h` isolating the artifacts). Monitor raw counts:
**ledger 31,620 events lost=0; refault 6,538 lost=0** — both within the §R3
≤1% bar. In-container INDEPENDENT verification (F6 — not trusting the
monitor's counts unchecked): ledger 31,622 lines, `shard_inodes_loaded=8`
breadcrumb, NO "Lost" line + NO LEDGER_END (docker-stop'd before detach, as
designed → drop=0), event histogram 15810 ADD + 15810 DEL (perfectly balanced —
every touched-extent ADD has a matching DEL, the eviction/re-fault cycle),
NO vmscan events (firehose gone), all 8 shard inodes (3300–4500 each, filter
intact). The refault probe BTF walk resolved (real inodes + extent-aligned
pgoffs). `r3_verify_cell.py` (post the two corrections below) → **VALID**.

## cap12g_instr_r3h — VALID (the clean instr cell; banked)

Result `r3_cap12g_instr_r3h_20260715.json`; ledger `_r3_cap12g_instr_r3h_ledger.log`
(31,620 events, drop=0 verified); refault `_r3_cap12g_instr_r3h_refault.log`
(6,538 events, lost=0); cachestat `_r3_cachestat_cap12g_instr_r3h_pass0..5.json`
(6 maps). Pass-boundary CLOCK_MONOTONIC ns recorded (6 marks). All R2 checks
PASS: swap 0, near_zero in 5 passes, pass-1 majflt 242,525≥50k, ms/fault
0.34–0.37 in [0.1,2.0], converged p50 18.42≥15, cg_delta active. Reproduces
12g_ctrl (majflt 242525→96638→139954→28662→17 across 5 passes vs ctrl's 4;
steady-state p50 18.42 vs 18.31). All R3 checks PASS: drop=0, pgoffs ⊆ inode
map, **refault probe vs kernel counter = 1.018** (2476... 6538 sampled ×512 =
3.35M vs cgroup `workingset_refault_file` total 3.29M — within 1.8%; per-pass
0.7–8.6%, most within 3%), **overhead 1.006× steady-state** (instr pass-5 18.42 /
ctrl pass-4 18.31, both majflt≈0–17). This is the clean 12g half of expectation
#1's attribution join.

**Note on the extra pass:** 12g r3h took 5 passes to converge (ctrl took 4).
The tracer's between-pass cachestat snapshots (`--cachestat-between-passes`,
6 syscalls across the cell) added memory pressure that aged the active list
faster and *regressed pass 3* to 139,954 faults (vs ctrl pass-3's 26,770).
This is exactly the observer-effect-on-reclaim-timing doc 15 §4 / artifact §5.1
warn about, and is WHY the overhead bar is compared at each cell's steady-state
pass (min majflt), not a fixed index. It does NOT affect the steady-state
verdict (1.006×) or the join (which slices by pass-boundary ns, not index).

## Verifier corrections (2026-07-16) — the REQ-3g INVALID verdicts revised

The REQ-3g verdicts above (both r3fix instr cells INVALID) were computed by
`r3_verify_cell.py` with TWO pre-sampling-era heuristic bugs. The monitor's
REQ-3g DONE-PARTIAL critique flagged this: "a heuristic written pre-sampling
flagging a designed property is a verifier bug, not a data defect." Both
corrected in commit fbb28e2, principled (not goalpost-moving — the original
checks compared against the wrong physical reference):

1. **`refault_within_2x_majflt` → `refault_probe_vs_kernel_counter`.** The old
   check compared probe_refault×512 against `majflt` within 2×. WRONG
   denominator: `workingset_refault` fires PER PAGE that finds a shadow entry;
   `majflt` counts readahead-coalesced I/O servicing events (~7× fewer on this
   kernel — measured 6.6–7.0× across BOTH instr cells, uniformly; NOT a
   broken-filter 0×/1000× signature). The correct reference is the cgroup's
   OWN `workingset_refault_file` counter; against it the ×512-scaled probe is
   within 0.3–1.8% total (12g r3h 1.018, 16g r3fix 1.003) and 0.7–8.6%
   per-pass. So the refault probe is SOUND, not a broken filter — the
   systematic ~7× vs majflt is the readahead-coalescing gap, designed-into
   the kernel's two differently-counted quantities, not a probe defect. The
   bar (2× sanity tolerance) is unchanged, now against the kernel's own refault
   counter. (Probe accuracy 1.003–1.018 is the real finding — a 1/512 sample
   reconstructing the kernel's own event count within ~1%.)

2. **`instr_overhead_le_1.10x` final-pass → steady-state (min-majflt) pass.**
   The two cells converge in DIFFERENT pass counts (12g r3h 5 vs ctrl 4 —
   tracing pressure delayed it), so a fixed pass-index is apples-to-oranges:
   12g r3h pass-3 is mid-sort (824 ms, majflt 139954) while 12g_ctrl pass-3 is
   near-converged (20.26 ms, majflt 26770) → a bogus 40.7× ratio. Uniform
   rule: each cell's most-converged pass (min majflt = the steady-state regime
   that cell actually reached). 12g → 1.006× (PASS). 16g → 1.120× (FAIL — see
   below). The pass-3 symmetric-transient (both cells at ~14k faults) recorded
   as a secondary signal in the detail (16g 1.072×, within bar).

**Honest REVISED verdicts:** 12g r3h **VALID** (all checks pass — banked, the
clean cell the join uses). 16g r3fix **INVALID only on the steady-state
overhead** (1.120×); its ledger (drop=0, 31620... 174992 events) and refault
probe (1.003 vs kernel counter — essentially perfect) are CLEAN and remain
join-usable for the 16g-side attribution. The 1.120× is likely inflated by the
heavier pre-drop probe: 16g r3fix ran with the 3 vmscan printf tracepoints
still active (~162k context events 16g bore — no storm, but real per-event
printf overhead) whereas the post-fix 12g r3h did not. A 16g re-run with the
light probe would likely clear the bar, but the monitor ruled the evidence set
complete (no more host cells); the 1.120× is recorded honestly with the cause
rather than chased through another ~1h host round for a 0.020× margin in the
residual-tail (artifact §5.1 non-steady) regime. Per F6 the 16g overhead FAIL
is RECORDED, not massaged.

## Evidence set COMPLETE (no more host cells) — proceeding to Phase D

The join's inputs are now all clean: 2 valid controls (cap16g/12g_ctrl,
latency-quotable + the inversion reproduced), 1 VALID instr cell (12g r3h,
clean ledger+refault+cachestat), 1 INVALID-only-overhead instr cell (16g r3fix,
clean ledger+refault+cachestat, overhead 1.120× recorded), 10+2 cachestat map
series (pre-fix REQ-2 + r3fix/r3h), + the query-extent map (40 queries, 10471
2 MiB extents). Phase D runs `r3_join_analysis.py` on the clean 12g r3h +
16g r3fix ledgers and verdicts the four §R3 pre-registered expectations below.

# R3 kernel-ledger — join analysis summary (2026-07-16)

Per-instrumented-cell join of ledger × refault × between-pass cachestat × query-extent map, on
(ino, pgoff→extent) and pass windows (doc 15 §2).

## Per-cell deliverables

### 12g_instr
- pass-boundaries: 6 ns marks
- ledger: 31620 events parsed, emitted=0, drop_rate=n/a
- refault distance: DOWNGRADED to activation-only (inst-3 limitation, recorded) — 6538 events
- pass-3 faulting extents: 4572; slow-tail queries (extents faulted): [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]...
- pass-3 per-query DEL: min/max=(1508, 2140) across 40/40 queries, skew(max/mean)=1.14 (the #1 concentration metric; ~1.0 = uniform, NOT a per-query slow tail)

### 16g_instr
- pass-boundaries: 6 ns marks
- ledger: 174992 events parsed, emitted=0, drop_rate=n/a
- refault distance: DOWNGRADED to activation-only (inst-3 limitation, recorded) — 2476 events
- pass-3 faulting extents: 341; slow-tail queries (extents faulted): [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]...
- pass-3 per-query DEL: min/max=(68, 171) across 40/40 queries, skew(max/mean)=1.32 (the #1 concentration metric; ~1.0 = uniform, NOT a per-query slow tail)

## Verdicts on the four §R3 pre-registered expectations

- **REFUTED** — 1_attribution (12g residual faults concentrated in slow-tail query extents (median untouched); ...): pass-3 per-query DEL extents: 12g min/max=(1508, 2140) across 40/40 queries, skew=1.14; 16g min/max=(68, 171) across 40/40, skew=1.32. Both skews ~1.0-1.4 = uniform spread, NOT slow-tail concentration.
- **UNCLEAR (downgraded: distance not extractable — activation-only, recorded)** — 2_decision_site (refault distance smaller at 12g; activation flips where distance>active_file...): 12g refaults=6538, 16g=2476; activation inferred downstream
- **CONFIRMED (asymmetry + 12g drain; 16g live-tracer drain observer-perturbed, pre-fix dead-tracer corroborates 10.93GB)** — 3_sort_pictured (16g holds the full load residue at pass0 (evicted~0) while 12g is already sheddi...): pass0 evicted: 12g=3.172GB / 16g=0.0GB → 16g held full / 12g shedding (asymmetry CONFIRMED); final cache: 12g=10.1301GB / 16g=13.4306GB (repeat-set ~10-11GB). 12g drained=True; 16g (live-tracer) drained=False — perturbed by live-tracer overhead (16g r3fix final 13.43GB vs pre-fix dead-tracer 10.93GB = clean drain, recorded observer effect, doc 15 §4).
- **CONFIRMED on drop + 12g (clean-probe) overhead; 16g overhead 1.120× recorded-FAIL (pre-drop heavier probe)** — 4_observer_effect (instrumented steady-state p50 ≤ 1.10× control; ledger drop ≤1%...): drop (verified-clean, no Lost line in stream): 12g=31620 events / 16g=174992 events — drop=0 both (overrun would show a Lost line or low count, e.g. REQ-3g 12g r3fix had lost=62145). Overhead (r3_verify_cell, steady-state): 12g r3h 1.006× PASS; 16g r3fix 1.120× FAIL (pre-drop heavier probe with vmscan printf firehose).

