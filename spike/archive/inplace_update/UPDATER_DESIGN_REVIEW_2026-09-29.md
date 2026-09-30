# Review of UPDATER_DESIGN.md — coordinator, 2026-09-29

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

Reviewed: `spike/archive/inplace_update/UPDATER_DESIGN.md` at commit `586e04ab`, read
in full, against `FORMAT_V3.md` as revised in `8005fb22`. Review by reading
only: nothing here is measured, no code was run.

Verdict: the plan/apply split, the recovery scan, the crash-window table and
the Dekker argument for the reader table are sound. U1 and U2 can make the
reuse gate miss a live reader and must be fixed before any run with a
concurrent reader. U3 decides whether the benchmark measures anything.

## Defects

**U1. Two incompatible reader tables.** The design registers readers in
`reader_table.bin` (1,024 slots × 16 B, "not in FORMAT_V3, the decoder does
not read it"). The revised spec creates `readers.bin` (256 slots × 64 B) and
the decoder is being extended to register there. A reader registered in one
file is invisible to an updater scanning the other, and the updater then
reuses content under it. One file, one layout: the spec's `readers.bin`;
the Python helper and the crate's `ReaderGuard` use it too.

**U2. Pid liveness is only valid inside one pid namespace.**
`kill(pid, 0)` returning ESRCH clears the slot. A reader in another pid
namespace (the MCP server is started through `docker exec`; a second
container mapping the same files) is reported ESRCH while alive, its slot
is cleared, and content is reused under it. "Pid reuse can only make the
updater wait longer" holds; this failure is the opposite direction. Fix:
a lease the reader refreshes (monotonic timestamp in the slot, the 64-byte
slot has room) with pid liveness only as a shortcut when the namespace id
recorded in the slot equals the updater's; or state "same pid namespace
only" as a hard precondition the updater checks and refuses otherwise.

**U3. Neither arm can place a new record on its first batch, and neither
can ever absorb net growth.** Holes come only from deleted or updated-old
docs. A2 and A2b (one flip) from a fresh copy place zero records (D2, D5),
and in steady state the number of placed docs is bounded by the number
freed, so a corpus that grows (new works exceed deletions) is never
absorbed by either arm. Brief §2.2 had the fallback: "record that fits no
hole → append at tail". Without it the head-to-head against A1 compares a
delta layer that ingests every document with an in-place arm that serves a
subset. Resolution: plan 06 addendum (fourth) pre-registers a `+tail`
variant; unplaced docs are reported for every arm as not served.

## Gaps

**U4. Writer I/O disagrees with the revised spec.** Spec (after R6): stores
through a `MAP_SHARED` mapping, `msync`, no `pwrite`. Design: `pwrite` for
unreachable bytes. Correct on Linux local files (one page cache); the two
documents must say the same thing. Either is acceptable for this spike; the
results file names what ran.

**U5. The power-loss model is the easy case.** "A write is durable iff an
fsync of its file completed after it" drops every un-synced write. A real
power loss keeps an arbitrary subset of dirty pages (writeback runs when it
likes), page by page, and that is the case the recovery scan exists for:
a posting word tagged e+2 on disk whose forward record never reached the
disk. The subset variant is in the design as "never part of the verdict".
It should be in the verdict, and at page granularity (4 KiB), not per
write.

**U6. D6 (hybrid rule not applied) is a deviation from a plan hard rule.**
Accepted for the reason given (no serving path merges short-list postings
from the delta layer), but it is a change to what plan 06 says will be
built, so it is recorded in the plan addendum, not only in results files.

**U7. B2's byte count needs a second reading.** `/proc/<pid>/io`
`write_bytes` counts dirtied pages: an 8-byte store into a clean page is
4,096 bytes. That is the honest device cost and stays the bar's number;
the logical bytes written are reported beside it so A2's scattered stores
and A1's sequential generation build can be compared on both.

## Checked and found correct

- Recovery rewrites (§5.1) keep each slot's visibility at E unchanged, so
  the scan can run under live readers.
- `old-at-fill` delete marks are tag-only and rollback-safe.
- Free-list rebuild by scan (§5.3) can leak a hole but cannot hand out a
  live one; a reused row always has at least one visible posting.
- A reader registered at e whose decoder later snapshots a newer epoch is
  covered (the registered epoch is the lower bound).
- R9: the row → W-id conversion happens inside the Rust binding and honours
  `row_id_override.bin`; ordinals and livedocs resolve from W-id strings.
  Not re-verified by the reviewer beyond the cited lines.
