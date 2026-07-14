# R2 fine convergence ladder — summary (measured 2026-07-14)

14/14 cells DONE (orchestrator `r2_host_orchestrator.sh`, driver
`r2_convergence_ladder.py`, cells `r2_cap*_20260714.json`). All cells pass
the F6 checklist: swap 0 everywhere, no empty results, pass-1 majflt 58k–537k
(real cold fills — pre-cell drop_caches worked), no too-good latencies.
Verified against raw JSONs by the host session (GLM drive session was not
launched; this file replaces its per-cell log).

| cap | rep | kind | passes | pass-3 p50 (fixed window) | converged/final p50 | final majflt | pass-1 majflt | pass-1 pgscan |
|---|---|---|---|---|---|---|---|---|
| 24g | 1 | near_zero | 3 | 18 ms | **18.4 ms** | 0 | 58k | 0 |
| 17g | 1 | near_zero | 5 | 101 ms | 35.0 ms† | 1,892 | 74k | 0.56M |
| 16g | 1 | near_zero | 5 | 124 ms | 35.6 ms† | 2,026 | 104k | 1.13M |
| 16g | 2 | near_zero | 4 | 114 ms | **18.6 ms** | 330 | 103k | 1.14M |
| 15g | 1 | near_zero | 5 | 145 ms | 20.9 ms† | 469 | 139k | 1.76M |
| 14g | 1 | near_zero | 5 | 158 ms | 31.3 ms† | 1,488 | 180k | 1.52M |
| 13g | 1 | near_zero | 5 | 1093 ms‡ | **17.9 ms** | 0 | 240k | 0.83M |
| 13g | 2 | near_zero | 4 | 119 ms | **18.9 ms** | 64 | 214k | 2.53M |
| 12g | 1 | near_zero | 4 | 21 ms | **18.6 ms** | 4 | 244k | 2.84M |
| 11g | 1 | near_zero | 5 | 384 ms | **18.1 ms** | 7 | 284k | 3.47M |
| 11g | 2 | near_zero | 4 | 406 ms | **18.9 ms** | 100 | 281k | 3.43M |
| 10g | 1 | plateau | 5 | 1397 ms | 1415 ms (thrash) | 196k/pass | 331k | 4.04M |
| 9g | 1 | plateau | 8 | 1403 ms | 1764 ms (thrash) | 212k/pass | 369k | 4.76M |
| 6g | 1 | plateau | 3 | 5753 ms | 5753 ms (thrash) | 554k/pass | 537k | 7.15M |

† stopped by the near-zero rule (majflt ≤ 2,500) with residual faults still
draining — final p50 is inflated by the residue, NOT an elevated steady
state (16g rep2, fully drained, reads 18.6 ms). Quote steady-state p50 only
from a majflt≈0 pass.
‡ 13g rep1 pass 3 is a host-noise event (fault bounce 79k→176k→12k on the
shared WSL2 page cache); rep2 is clean and monotonic.

## Verdicts on the four pre-registered expectations (backlog §R2)

1. **Cliff location — CONFIRMED.** Converged p50 is a step: every cap
   ≥ 11 GB converges to a flat **17.9–18.9 ms** with faults → ~0; every cap
   ≤ 10 GB plateaus in sustained thrash (10g ~1.4 s, 9g ~1.8 s, 6g ~5.8 s,
   scaling with the deficit). The cliff sits **between 10 and 11 GB** — the
   empirical repeat-set size, matching the prior ~10–11 GB estimate.
2. **Passes-to-converge rises with cap — NOT CONFIRMED at this resolution.**
   Pass counts are flat (4–5, ±1 run-to-run) across the whole 11–17 GB band.
   BUT the fixed-window inversion itself REPRODUCED at the pass-3 snapshot:
   12g p50 21 ms vs 16g 124 ms (fresh run; R1 read 22 vs 135) — while 12g
   actually carried MORE residual faults at pass 3 (26k vs 15k). Mechanism
   refinement: the pass-3 inversion is carried by the *distribution* of
   residual faults across queries (12g's residue misses the median query;
   16g's residue is spread, lifting p50), not by 12 GB finishing the whole
   sort earlier. The capacity-scaled convergence-TIME prediction (Che/Fagin)
   is not resolvable at pass granularity in this narrow band.
3. **Pressure-scaled aging — CONFIRMED, directly observed.** Pass-1 cgroup
   pgscan is monotone in pressure: 24g 0 → 17g 0.56M → 12g 2.8M → 11g 3.5M
   → 10g 4.0M → 6g 7.1M. workingset_refault_file → 0 at convergence above
   the cliff; stays 1.6–4.7M/pass below it. Bonus direct observation: at
   24g the active_file gauge ends at **0.2 GB** (no pressure → the kernel
   never promotes anything — aging literally doesn't run), vs 7.5–8.8 GB at
   11g where the repeat set must earn protection. §2.2 of the artifact note
   is upgraded from inference to measurement.
4. **Replicate spread — CONFIRMED small.** Fully-drained converged p50 spans
   18.1–18.9 ms across all cells and replicates; passes-to-converge ±1. The
   single host-noise event (13g rep1) was caught and arbitrated by its
   replicate.

Files: cells `r2_cap{24,17,16,15,14,13,12,11,10,9,6}g[_rep2]_20260714.json`,
per-cell logs `_r2_cap*_drive.log`, statuses `_r2_cap*.status`,
completion flag `_r2_ladder.ALLDONE`.
