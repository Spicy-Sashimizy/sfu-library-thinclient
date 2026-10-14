# patches/ — never-merged `inplace-v3` fork commits (record)

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

The five `seismic_upstream_inplace_v3*.patch` files are the spike commits of the
SEISMIC fork branch `inplace-v3` (a3173d1..328bf51; `seismic_upstream_inplace_v3_b1_guard.patch`
is c7b4b54 on branch `b1-guard`): the v3 encoder/decoder, the A2b unit read path,
guards, the +tail variant and the A2b oracle fix. That branch was **never merged**
into the fork's `main` (reset to 2c4d863 on 2026-09-30); the served `.so` never
contained them, and the owner decided 2026-09-30 not to merge (+1.3 % B1 per-query
cost on the serving path). The patch files are left byte-exact (banner kept here,
not prepended) so the ones with a `From <sha>` mbox header still apply with
`git am`. Full record: `docs/archive/inplace_update/README.md`.
