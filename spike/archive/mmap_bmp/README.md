# mmap-BMP spike

> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

The ~1–2 day feasibility spike that gates the whole "immutable no-JVM unified
sparse engine" idea. **Question: does an mmap'd BMP keep RssAnon ~0 (cure the
floor) and return identical results, with an acceptable cold-p95?**

Full rationale: `docs/archive/qdrant_vs_lucene_assessment/ARCHITECTURE_EXPLAINER.md` §6 and
`MMAP_BMP_SPIKE.md`. Engine project: `docs/archive/sparse_engine_project/`.

## Files
| File | What |
|---|---|
| `record_baseline.py` | STEP 1 — stock (load-into-RAM) BMP over the test `.bmp` shards; saves top-k + RSS + latency + the encoded query vectors. **Runnable now.** |
| `FORK_BMP.md` | STEP 1.5 — the exact Rust change (swap `Vec` read → `memmap2::Mmap`). Built into a throwaway venv. |
| `compare_fork.py` | STEP 2 — forked mmap BMP; replays saved qvecs; checks G1 correctness / G2 RAM / G3 latency. |

## Run
```bash
# 1. baseline (serving venv — has the SPLADE encoder):
.venv/bin/python3 spike/mmap_bmp/record_baseline.py

# 2. fork per FORK_BMP.md, then:
MMAP_BMP_SITE=<throwaway-venv>/lib/python3.11/site-packages \
  <throwaway-venv>/bin/python3 spike/mmap_bmp/compare_fork.py
```

## Gates (decide build-vs-kill)
- **G1 correctness** [HARD]: mmap top-k == stock, byte-identical.
- **G2 RAM** [HARD]: RssAnon ~0 after load (page-cache only) — the whole point.
- **G3 latency** [signal]: cold p50/p95 vs warm; warm ≤ stock; cold within ~2–3× warm
  at section scale ⇒ GREEN to build the engine. Cold blow-up ⇒ kill cheaply.

## Isolation (this container serves the MCP)
- Branch only (`spike/mmap-bmp`); never install the fork into `.venv`.
- Keep clone + Rust `target/` + `out/` in the scratchpad / gitignored.

`out/` is gitignored — it holds local baseline/qvec JSON, not source.
</content>
