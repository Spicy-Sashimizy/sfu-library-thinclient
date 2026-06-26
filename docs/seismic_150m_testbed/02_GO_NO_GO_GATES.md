# 02 · Go / No-Go Gates

HARD = a fail kills/blocks that path. SIGNAL = informs, doesn't auto-kill.
Thresholds are the decision numbers; record the actual value next to each when run.
Phases: **P0** desk/fact-find → **P1** persona-scale standalone (Path A) →
**P2** RAM + pruning at scale → **P3** quality parity → **P4** 150M serve →
**P5** build-vs-buy decision (Path C vs B).

| Gate | Phase | Type | PASS condition | Why this number | Measured |
|---|---|---|---|---|---|
| **GZ Fact-find** | P0 | HARD | SEISMIC (a) prunes at ≥100M scale in the literature AND (b) is no-JVM/embeddable | if pruning isn't validated at scale, it's just BMP again; if it's JVM-only, it loses the whole point vs OpenSearch | ✅ **PASS 2026-06-26** — 138M MS MARCO v2 (ECIR 2025); pure-Rust MIT `pyseismic-lsr`. **Caveat: no mmap in FOSS impl** → G-RAM is the open risk. See `06_FINDINGS.md`. |
| **G1 Build (persona)** | P1 | HARD | SEISMIC index builds from the stored SPLADE `sparse_field` (med_bio persona) with no re-encode; build completes without OOM | proves the existing vectors feed SEISMIC unchanged | ✅ **PASS 2026-06-26** — 2M med_bio builds in 187s, peak RSS 2.81 GB, on-disk 1.69 GB, 27,896 vocab. `seismic_build_persona_2m.json`/`_929k`. See `06_FINDINGS.md`. |
| **G2 Quality (persona)** | P1 | HARD | top-k overlap@10 vs Qdrant ≥ 0.95 at matched params; per-leg NDCG@10 within noise | the leg must return the same papers we validated | ❌ **FAIL 2026-06-26** — overlap@10 0.479 (<0.95), 34-common, Qdrant scoped to the same 2M oaids. Stable across heap_factor {0.8,0.5,0.0} → static index-time pruning (n_postings/max_fraction), not query-tunable. NDCG common-judged 1/34 (under-powered). Recovery = index-time param sweep + rebuild (OPEN). `seismic_parity_persona_2m.json`+`_heapfactor_sweep.json`. |
| **G3 RAM floor (standalone)** | P2 | HARD | measure resident RAM/doc for Path A, **broken into forward-index vs inverted/block/summary side**; **if it confirms ~RAM-resident** (≳ Qdrant's 43 B/pt → > 6.55 GB @150M proj.), Path A is RAM-NO-GO and the decision routes to B-vs-C | the gate-zero risk, now measured not assumed; this is the number that forces the build-vs-buy fork. **The forward/inverted split decides whether the cheap Path C (Lance-ify the forward index only) can cure most of the floor, or whether the whole index must move** (`01_ARCHITECTURE.md` Path C). Mirrors the mmap-BMP finding that forward was ~100% of anon at 1M but the inverted side became the ~50 GB floor at persona — so measure both sides at ≥2 corpus sizes, don't assume which dominates. | ❌ **FAIL (Path A RAM-NO-GO) 2026-06-26** — as gate-zero predicted. RssAnon ≈ 100% of index Total (RAM-resident). 2M → 912 B/doc → 150M proj 137 GB (≫ Qdrant 43 B/doc / 6.55 GB). **Split at 2M: forward 628 MB / inverted+summary 1.03 GB = 62% → the INVERTED side dominates → cheap Path C (mmap forward-only) ruled out; the WHOLE index must move.** Routes to B-vs-C (G9). `seismic_ram_floor_persona_2m.json`+`_929k`. |
| **G4 Pruning sub-linearity** | P2 | HARD | `candidates_scored / corpus` **falls** as corpus grows (sub-linear) across a ≥2× corpus jump — the test BMP **failed** (ratio stayed ~0.95) | confirms SEISMIC's selectivity is real on *our* 64-term SPLADE queries, not just paper queries | ✅ **PASS (sub-linear) 2026-06-26** — the decisive gate. Instrumented `search_with_stats` (visited.len). Worst-query ratio 0.0198→0.0092 across a 2.15× corpus jump (0.93M→2.0M, same 34 queries); both <2% vs BMP's ~0.95. SEISMIC prunes where BMP couldn't. `seismic_pruning_persona.json`; instrumented fork `spike/seismic_testbed_instrumented/README.md`. |
| **G5 Latency (persona)** | P2 | SIGNAL | warm p50 ≤ Qdrant persona 66 ms on equal hardware | competitive serving at the tier we can measure locally | ⬜ |
| **G6 RRF parity (system)** | P3 | HARD | full-pipeline RRF NDCG@10 within **±0.005** of current stack (0.560), LLM-judged; degrade paths intact | no system-level quality regression | ⬜ |
| **G7 150M build** | P4 | HARD | full 150M SEISMIC index builds without OOM on an available/justified host; on-disk size recorded | the target scale is the whole point | ⬜ |
| **G8 150M RAM + latency** | P4 | HARD | served 150M resident RAM **flat / materially < Qdrant 6.55 GB** (Path C) OR characterized RAM-bound point (Path A); p50 in a usable band | proves (or kills) the RAM cure at scale | ⬜ |
| **G9 Ownership** | P5 | HARD | Path C total cost (build + per-arch wheels + SEISMIC-fork upkeep) **<** value of no-JVM over Path B (OpenSearch+SEISMIC, zero new code) | the R-OWN build-vs-buy call, decided explicitly with numbers | ⬜ |

## Kill criteria (explicit)

- **G2/G6 fail** (quality drifts) → SEISMIC isn't faithful to the validated recipe →
  **KILL** SEISMIC; stay on Qdrant / size the host.
- **G4 fails** (pruning linear on our queries, like BMP) → the 138M paper result
  doesn't transfer to our query distribution → **KILL**; SEISMIC offers nothing BMP
  didn't. *(This is the single most important gate — it's the exact axis BMP died on.)*
- **G3 fails AND Path C not worth building (G9)** → no cheap no-JVM RAM cure →
  **NO-GO on no-JVM**; fall back to **OpenSearch+SEISMIC** (JVM, bounded heap) or a
  bigger Qdrant box. This is an acceptable, documented landing — not a failure of the
  testbed, which exists precisely to find it cheaply.
- **G7/G8 fail at 150M** (OOM on build, or RAM not actually cured at scale) → the
  persona greens didn't extrapolate → **KILL** Path C; same fallback as above.

## Cheapest path to a confident decision

P0 (done) → P1/P2 on the existing med_bio persona shards (no 150M host needed) gets
you G2 (quality), G3 (RAM/doc), G4 (pruning) — **the three gates that decide
everything** — for the cost of one `pyseismic-lsr` install + the existing parity
harness, on the 31.6 GB host. Only if those green do you spend a 150M host (P4) or a
Path-C build (P5).
