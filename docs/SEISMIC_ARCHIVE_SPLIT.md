# Seismic-only dev container + BMP/Qdrant archival split (2026-07-06)

**Status:** ACTIVE — **Phase A (SEISMIC default promotion) DONE 2026-07-06 — commit-linked
below. Phases B–E (the physical split) are planned, not yet executed.**

This doc is the canonical map for splitting this dev container into (1) a
**Seismic-only serving line** and (2) an **archival container**
(`sfu-library-archive`) that carries the BMP and Qdrant lines for
testing/forensics, with the SPLADE db (Qdrant `splade_150m`) staying reachable
over HTTP. Planning lineage: `.claude/plans/seismic-only-dev-container-and-
archive-split.md` (superseded by this doc).

---

## 1. Interaction map — what talks to what today

Everything the serving path touches, with the split boundary marked. `[KEEP]`
stays in this dev container; `[CUT→ARCHIVE]` moves; `[CUT-BACK]` is the
reconnect line that crosses containers after the split.

```
MCP server (src/sfu_library_mcp_server.py / _http.py, venv .venv/)
 └─ lib/tools.py → FederatedSearchRouter → ThinClientRetriever      [KEEP]
     ├─ BM25F leg ── tantivy ← data/thinclient_index/sections/      [KEEP]
     ├─ Dense leg ── usearch ← data/thinclient_index/dense/
     │                + dense_cache.py warm cache                   [KEEP]
     ├─ SPLADE leg ── SFU_SPLADE_BACKEND selects ONE of:
     │   ├─ seismic (DEFAULT 2026-07-06)                            [KEEP]
     │   │   ├─ ParallelSeismicBackend / SequentialSeismicBackend
     │   │   │   (src/lib/thinclient/sharded_seismic_backend.py)
     │   │   ├─ manifest: data/eval_results/
     │   │   │   seismic_c25_shards_150m_mmap_dotvbyte.json (code default)
     │   │   ├─ shards: data/seismic_150m/index/plan01/
     │   │   │   global_shard{0..7}of8.dotvbyte.mmap  (~32 GB)      [KEEP]
     │   │   ├─ f16 twins: global_shard{0..7}of8.mmap (~62 GB)
     │   │   │   — PARITY REFERENCE for every gate-a run,
     │   │   │   doc 12 §5: do not delete                           [KEEP]
     │   │   └─ seismic .so (venv) ← built from spike/seismic_upstream
     │   │       + spike/vectorium_fork (dv kernel)                 [KEEP]
     │   ├─ qdrant (fallback; default 2026-06-24→2026-07-06)   [CUT→ARCHIVE]
     │   │   ├─ HTTP :6333 ← .tools/qdrant/qdrant binary
     │   │   ├─ storage: data/qdrant_spike/storage/ (202 GB,
     │   │   │   collection splade_150m — "the SPLADE db")
     │   │   ├─ ingest: scripts/archive/spike_qdrant_sparse.py +
     │   │   │   scripts/archive/bmp_ingest_watchdog.sh (auto-restarts
     │   │   │   qdrant — MUST be disabled before the move)
     │   │   └─ reconnect: SFU_SPLADE_QDRANT_URL=<archive:6343>  [CUT-BACK]
     │   └─ bmp (forensics)                                    [CUT→ARCHIVE]
     │       ├─ 150M .bmp artifacts: DELETED 2026-06-25
     │       ├─ 1M testbed: data/thinclient_1m/sections/*.bmp (2.3 GB)
     │       ├─ POC: data/thin_client_poc/ (~1 GB)
     │       └─ research spike: spike/archive/mmap_bmp/ (9.8 GB)
     ├─ SPLADE query encoder ── models/splade_onnx[_fp16] (15 GB)
     │   — SHARED by ALL THREE sparse backends; the archive
     │   container needs its own COPY (not a move)          [KEEP + COPY]
     ├─ meta.sqlite (24 GB) + abstracts sidecars + packed/ (42 GB)  [KEEP]
     └─ RRF fusion (federated_search.py, k=60)                      [KEEP]

Build sources (feed BOTH lines — cut only WITH their consumers):
 ├─ data/thinclient_index/spool_backup/ (123 GB, 5 sections)
 │   → source for BOTH the Qdrant ingest AND the Seismic G7 shard
 │   builds (the 2026-07-01 rebuild ran from it). DO NOT DELETE;
 │   move to archive/cold storage only after the Seismic shards +
 │   f16 twins are verified on persistent paths.            [DECISION A]
 └─ data/openalex_snapshot/ (55 GB, download/indexer checkpoints)
     → only needed to resume/extend corpus ingest (the 250M
     target). Archive unless an extension is planned.       [DECISION B]
```

## 2. What is being cut out, and what must be cut back in

| Cut out (→ `sfu-library-archive`) | Size | The cut line (what breaks) | The cut-back line (how it reconnects) |
|---|---|---|---|
| Qdrant process + `data/qdrant_spike/storage` | 202 GB | `retriever._splade_leg_qdrant` can no longer reach `localhost:6333` | `SFU_SPLADE_BACKEND=qdrant` + `SFU_SPLADE_QDRANT_URL=http://<archive-host>:6343` — the retriever already reads both env vars, zero code change. **Constraint: Qdrant storage is single-writer file-locked → exactly ONE process owns it; sharing is HTTP-only, never a shared bind-mount.** |
| `.tools/qdrant/` binary + `bmp_ingest_watchdog.sh` duty | 82 MB | watchdog would restart a Qdrant this container no longer owns — disable it here BEFORE the move | runs in the archive container instead |
| BMP 1M testbed (`data/thinclient_1m`), POC (`data/thin_client_poc`), `spike/mmap_bmp` | ~13 GB | nothing in the served path (BMP leg is env-gated and its 150M artifacts are already gone) | archive container checks out branch `archive/bmp-qdrant`; BMP/Qdrant code stays alive there (and in git history here) |
| `models/splade_onnx*` | 15 GB | — (COPY, not cut: both containers need the encoder) | plain file copy |

**Explicitly NOT cut** (things that look archival but are load-bearing here):
f16 twin shards (parity reference for every gate-a run), `spool_backup`
(regeneration source for the served Seismic shards themselves),
`seismic_c25_shards_150m_mmap.json` (f16 manifest — parity harnesses), the
committed Qdrant baseline records under `data/eval_results/` (the rejudge/
parity harnesses read STORED records, so they keep working with no live
Qdrant).

## 3. Phase A — SEISMIC promoted to default (DONE 2026-07-06)

Upgrade-readiness was re-verified against the doc trail before flipping —
every serve gate is green in the canonical docs:

| Gate | Verdict | Canonical record |
|---|---|---|
| G6 system parity (HARD) | **PASS** (re-scoped paired-delta 2026-06-30): SEISMIC leg NDCG@10 0.9262 vs Qdrant 0.9065, Δ=+0.0197, 95% CI +0.0098..+0.0297 clears zero, n=120 | `02_GO_NO_GO_GATES.md`, `rejudge_kimi_seismic_n120_20260630_2137.json` |
| G7 150M build (HARD) | PASS 2026-06-28; rebuilt to persistent paths 2026-07-01, end-to-end verified | `06_FINDINGS.md` |
| C2.5 mmap serve | MMAP_SERVE_READY (anon Δ 0.0 GB, bit-identical parity) | `seismic_c25_shards_150m_mmap*.json` |
| dv format (served layout) | PROMOTED (E7b/G8b): 25.23 GB RSS vs f16 41.86 GB, latency-neutral ~65 ms; **the only layout that fits this 32 GB container** | doc 10 §7.5, `g8b_fullcorpus_*` |
| dv parity caveat | corpus 0.9906 accepted 2026-07-05; shards 1–2 = 0.985 — **E8 (dv-v2 per-doc scale) is the pre-registered recovery lever**, doc 12 Q1 | doc 10 §7.6 |

Changes shipped (same commit as this doc):

1. `SFU_SPLADE_BACKEND` default `qdrant` → **`seismic`** (`retriever.py`).
2. Unset `SFU_SEISMIC_SHARD_MANIFEST` now defaults to the dv manifest
   (`seismic_c25_shards_150m_mmap_dotvbyte.json`) when present **and the
   retriever serves the real `data/thinclient_index` root** → the promoted
   container serves SEISMIC with zero env config, while synthetic/test
   index_roots never silently load the 150M corpus. Set env always wins.
3. Pre-flip bug fixes (from the 2026-07-06 serving-path review):
   filtered-query over-fetch in `_splade_leg_seismic` (was fetching exactly
   `top_k` then post-filtering — now `top_k × OVERFETCH_FILTERED`, the
   Qdrant/BMP convention) and `_load_manifest` partial-manifest guards
   (mixed/short manifests now raise instead of silently serving a partial
   corpus). Relative manifest/shard paths re-anchor at the repo root (MCP
   server cwd ≠ repo root).
4. Guard tests: `test_served_seismic_path.py` +3 (default-is-seismic,
   partial-manifest-refusal, filtered-leg over-fetch) — 17/17 pass.

Env matrix after the flip (all optional in this container):

| Env | Default | Meaning |
|---|---|---|
| `SFU_SPLADE_BACKEND` | `seismic` | `qdrant` = rollback, `bmp` = forensics |
| `SFU_SEISMIC_SHARD_MANIFEST` | dv manifest (code default) | any C2.5-shape manifest |
| `SFU_SEISMIC_LOAD_MODE` | `mmap` | `stock` = Path-A (persona scale only) |
| `SFU_SEISMIC_FEDERATION` | FS-aware since 2026-07-18 (sequential on 9p/NFS, parallel on local disk); was `parallel` | `sequential` = ~1-shard resident bound; set env always wins |
| `SFU_SEISMIC_K_PRIME` / `_QUERY_CUT` / `_HEAP_FACTOR` | max(2×k, 100) / all / 0.8 | over-fetch knobs (k′ cell corrected 2026-09-01 to match `retriever.py`; was listed 4×k) |
| `SFU_SPLADE_QDRANT_URL` | `http://localhost:6333` | the cut-back line post-split |

**Rollback at any point:** `SFU_SPLADE_BACKEND=qdrant` (+ the URL env once
Qdrant lives in the archive container).

## 4. Phases B–E — the physical split (PLANNED, in order)

- **B — archive container + branch.** Create ClaudeBox project
  `sfu-library-archive`; push branch `archive/bmp-qdrant` (cut from
  `spike/mmap-bmp`); archive clones at that branch; copy `.tools/qdrant/`,
  `models/splade_onnx*`; venv per house rules.
- **C — move the SPLADE db.** Disable `bmp_ingest_watchdog.sh` here; stop
  Qdrant; **move `data/qdrant_spike/` from the WSL2 host side** (same C:
  volume → instant rename; an in-container `mv` is a 202 GB copy). Bring up
  in archive with `QDRANT__STORAGE__STORAGE_PATH`, host port **6343**. Smoke:
  collection point-count + one query vs a committed parity record.
- **D — clear remaining non-Seismic paths.** `thinclient_1m`,
  `thin_client_poc`, `spike/mmap_bmp` → archive; `tmpclaude-*`,
  `.handoff_extract`, `sfu library mcp-handoff.zip` → delete;
  `dense_compression`, `sectioned`, `thinclient_test_resume` → archive after
  their result JSONs are confirmed committed. Resolve **DECISION A**
  (spool_backup — recommend archive, never delete) and **DECISION B**
  (openalex_snapshot — archive unless the 250M extension is planned).
- **E — verify + doc sync.** Full test suite + live `search_academic` with
  all three legs healthy; Rule Zero audit (`find data/seismic_150m -newermt
  <start>` → empty); update this doc's status line, `THIN_CLIENT_SWAP.md`,
  `STORAGE_BUDGET_150M.md` (new resident/disk numbers), `docs/README.md` —
  same push as the move.

End state: dev container ~236 GB (Seismic line + serving stack), ~390 GB
moved/freed. Nothing destructive before archive copies are verified.
