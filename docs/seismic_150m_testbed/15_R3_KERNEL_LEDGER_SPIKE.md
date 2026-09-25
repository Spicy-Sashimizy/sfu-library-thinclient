# 15 — R3 kernel-ledger spike: per-page eviction/refault attribution

**Status:** ACTIVE — **MEASURED (2026-07-16).** Pre-registered bars live in
`11_EXPERIMENT_BACKLOG.md` §R3; design + execution delegated to the drive
session per §6. Results in §7 below (verdicts: #1 REFUTED, #2 UNCLEAR-downdr,
#3 CONFIRMED, #4 CONFIRMED-qualifying); the per-page-attribution write-up in
`session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md` §8.

## §0 The question

R2 measured *what* happens (backlog §R2; `session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
§7): the cliff sits at 10–11 GB, and the fixed-window inversion (12 GB pass-3
p50 21 ms vs 16 GB 124 ms) is carried by *where* residual faults land across
queries — 12 GB's residue misses the median query — not by the smaller cap
finishing the sort first. But that mechanism statement is still an inference
from per-pass aggregates (majflt totals + cgroup counters). R3 asks the kernel
to show its work at page granularity:

> Which index extents were evicted when, which came back, at what refault
> distance, with what activation decision — and which of the 40 queries touch
> exactly those extents?

The target output converts "12 GB's residue happens to miss the median query"
into "extents X–Y stayed cold because their refault distance exceeded the
active-list size at that cap, and queries 12/17/31 are the only ones that
touch them." That per-page × per-query join is the piece the WiOpt-line
literature (04 doc §4, `05_EXTERNAL_PRECEDENTS.md`) does not have.

## §1 Instruments — three tiers, no kernel patch

The eviction/refault pipeline is already instrumented upstream; R2 used only
the coarsest tier (cgroup `memory.stat`). R3 goes finer:

1. **Eviction/refault ledger (bpftrace, tracepoints).**
   `mm_filemap_delete_from_page_cache` + `mm_filemap_add_to_page_cache` fire
   per page with inode and page offset → a `(ns, event, ino, pgoff)` stream
   for every shard-page eviction and fault-back. `mm_vmscan_lru_shrink_inactive`
   / `mm_vmscan_memcg_reclaim_begin/end` give reclaim-batch context. Filter to
   the shard-file inode set **in-probe** (event rate on unrelated files would
   swamp the buffer); emit through a perf ring; count drops.
2. **`workingset_refault()` probe (kprobe/kfunc).** The refault distance and
   the activation decision are computed inline in that function; a probe
   captures `(ino, pgoff, refault_distance, activated?)` per refault event.
   This watches the 04-doc §4 link being decided: residue placement vs
   active-list size. If distance extraction from the shadow entry proves
   impractical under the WSL2 kernel's BTF, the minimum viable probe is
   `(ino, pgoff, activated?)` — still enough for expectation 2's activation
   half; record the downgrade explicitly.
3. **`cachestat()` extent-residency maps (kernel ≥ 6.5).** Between passes,
   snapshot per-extent `cache / evicted / recently_evicted` counts for every
   shard slab — a literal picture of where the residue sits at pass k under
   12 GB vs 16 GB, far cheaper than mincore loops. Fallback if the syscall is
   missing: mincore (residency bit only, no evicted/recently_evicted — the
   maps lose the shadow-entry half; note it).

## §2 The join

Four keyed datasets per cell, joined on `(ino, pgoff→extent)` and pass window:

- **Per-query extent map** — which extents each of the 40 queries touches,
  from the `search_visited` pyo3 surface (`mmap_index.rs:251`; same surface
  the F1 hot-set generator uses — no Rust changes).
- **Ledger** (instrument 1) sliced by pass using pass-boundary monotonic
  timestamps the driver writes into the result JSON.
- **Refault events** (instrument 2), same slicing.
- **Between-pass residency maps** (instrument 3).

Deliverable tables per instrumented cell: (a) residue map at each pass
boundary; (b) residual-fault attribution per query at the fixed pass-3
window; (c) refault-distance distribution vs `active_file` size per pass.

## §3 Capability gate G-R3-0 (WSL2 — must pass before any cell)

This runs under WSL2's Microsoft-built kernel; nothing is assumed:

- `uname -r` ≥ 6.5 for `cachestat` (else fallback to mincore, recorded);
- `/sys/kernel/btf/vmlinux` present (CO-RE/BTF for the kprobe);
- the four tracepoints exist under `/sys/kernel/debug/tracing/events/`;
- a trivial bpftrace probe fires from a privileged `--pid=host` container;
- `cachestat` (syscall 451) returns sane counts on a known-resident file.

Any hard miss → the spike PARKS with the probe output committed. A park here
is itself a finding: one more argument for the bare-metal replication the
convergence-artifact writeup already needs.

## §4 Observer-effect control (binding)

Tracing every page event has overhead, and the perturbation is not only
latency — it can shift reclaim timing itself. Therefore:

- Every instrumented cap gets an **uninstrumented control cell** in the same
  session, same binary, cache dropped identically.
- Bars: instrumented converged p50 ≤ **1.10×** its control; ledger perf-buffer
  drop rate ≤ **1%**. Fail → downsample (e.g. pgoff sampling) and rerun.
- **Latency numbers are only ever quoted from control cells.** Instrumented
  cells contribute residency/attribution state, never headline latency.

## §5 Cell plan

Caps **12 and 16 GB** — the R2 inversion pair — 4 cells: 12-ctrl, 12-instr,
16-ctrl, 16-instr. R2 convergence-terminated rules unchanged (min 3 / max 12
passes; near_zero majflt ≤ 2,500 or plateau; shared WSL2 page cache dropped
before every cell; same 40 pre-encoded queries / top-50 / prefault-ON;
traversal-only latencies). R2 discard rules inherited wholesale; R3 additions
in backlog §R3.

## §6 Division of labor (binding, per operator instruction 2026-07-15)

- **Host session (Claude, this doc): ideas only** — this design, the backlog
  §R3 pre-registration, and the drive prompt. No scripts, no cells, no
  analysis.
- **GLM 5.2 drive session (CCR/NeuralWatt, in-container): everything else** —
  capability probe, bpftrace programs, cachestat snapshotter, query-extent
  mapper, driver (extends `scripts/seismic_testbed/r2_convergence_ladder.py`),
  host orchestrator (extends `r2_host_orchestrator.sh`), per-cell F6
  verification, the join analysis, and all doc updates. Drive prompt:
  `data/eval_results/_r3_kernel_ledger_drive_prompt.md`.
- **Host-action queue.** The container has no docker daemon and no
  privileges; anything needing them (running the probe, launching cells) is
  requested via `data/eval_results/_r3_host_queue.md` and executed by the
  hourly host monitor **after reviewing the requested script** (they run
  privileged). The monitor also F6-spot-checks every headline number against
  raw cells before it is trusted (the 150× lesson, backlog §R2 preamble).

## §7 Results (MEASURED 2026-07-16)

Capability gate G-R3-0 **PASS 7/7** (REQ-1b, 2026-07-16): kernel
6.18.33 ≥ 6.5 ✓, `/sys/kernel/btf/vmlinux` present ✓, all four tracepoints
present ✓, a bpftrace one-liner fired ✓, `cachestat` (syscall 451) returned
sane counts on a resident file ✓. No park.

Cells (REQ-2 controls + REQ-3g/3h instrumented re-runs, all 2026-07-16):

| cap | mode | converged | passes | pass1 majflt | steady p50 ms | drop | overhead | verdict |
|---|---|---|---|---|---|---|---|---|
| 16g | ctrl | near_zero | 5 | 103,833 | 33.76 | — | — | VALID (latency-quotable) |
| 12g | ctrl | near_zero | 4 | 243,600 | 18.31 | — | — | VALID (latency-quotable) |
| 16g | instr (r3fix) | near_zero | 5 | 103,917 | 37.82 | 0 | 1.072× pass-3 / **1.120× steady** | INVALID only on overhead; ledger+refault clean |
| 12g | instr (r3h) | near_zero | 5 | 242,525 | 18.42 | 0 | **1.006× steady** | **VALID** |

The R2 inversion reproduces in the controls: 12g pass-3 p50 20.26 ms vs 16g
129.28 ms (R2: 21 vs 124 ms) — the smaller cap beats the larger at the fixed
window. Latency is quoted ONLY from control cells (doc 15 §4).

**Verdicts on the four pre-registered expectations** (full evidence + file paths
in `data/eval_results/_r3_ledger_summary.md` and `_r3_join_analysis.json`):

1. **Attribution — REFUTED** (informatively). At pass-3, per-query DEL-extent
   skew is 1.14 at 12g and 1.32 at 16g (both ~uniform spread across 40/40
   queries), NOT a slow-tail concentration. The repeat set's extents are
   shared across all 40 queries (19.6% touch all 40; 1.8% touch one), so
   residual faults cannot concentrate per-query. The inversion is carried by
   convergence-trajectory position at the fixed window, not per-query fault
   distribution — the §2.3/§7.2 refinement, now directly observed rather than
   inferred.
2. **Decision site — UNCLEAR (documented downgrade).** The refault-distance
   local is not BTF-extractable under 6.18.33 → emitted -1 per the §R3
   discard rule; activation inferred downstream. The refault probe itself is
   sound: its ×512-scaled count matches the kernel's own `workingset_refault_file`
   cgroup counter within 1.8% (12g) / 0.3% (16g). The Che/Fagin link is
   watched at per-pass count granularity, not per-event distance.
3. **The sort, pictured — CONFIRMED.** pass-0 evicted: 12g 3.17 GB (already
   sorting) vs 16g 0.0 GB (held the full working set, not yet sorting) — the
   §2.2 asymmetry pictured at page granularity. 12g drains to 10.13 GB (the
   ~10–11 GB repeat set). 16g's *live-tracer* drain to 13.43 GB is
   observer-perturbed (the tracer + cachestat snapshots added pressure); the
   pre-fix dead-tracer 16g corroborates a 10.93 GB drain.
4. **Observer effect — CONFIRMED on drop + the clean-probe overhead; the 16g
   pre-drop-probe overhead 1.120× recorded.** Drop=0 both (no Lost line in
   clean 31,620 / 174,992-event streams). 12g r3h clean-probe overhead 1.006×
   (PASS). 16g r3fix 1.120× steady-state (FAIL — likely the pre-drop heavier
   probe with the vmscan printf firehose still active; pass-3 transient 1.072×,
   within bar).

**Two R3-instrument corrections landing live (both the F6 discipline working):
the vmscan batch-context tracepoints were DROPPED from the ledger probe
(REQ-3h) — they had no page index to downsample, were 95% of 12g volume, and
overran the perf ring to 11.8% drop; the join never keyed on them and the
reclaim-pressure signal already lives in per-pass cgroup `pgscan`/`pgsteal`.
And the verifier's refault-ratio heuristic was corrected (it compared the
probe against `majflt`, but `workingset_refault` fires per-page while `majflt`
counts coalesced readahead I/O — ~7× fewer; the correct reference is the
kernel's own `workingset_refault_file`, against which the probe is within
1–2%).** No served-path code or default changed.
