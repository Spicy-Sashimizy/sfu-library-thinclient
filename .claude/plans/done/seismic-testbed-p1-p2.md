# SEISMIC 150M testbed — implement P1 (persona build) + P2 (the 3 deciding gates)

Implements `docs/seismic_150m_testbed/04_BUILD_AND_GATHER.md` phases P1–P2 on the
**existing 31.6 GB host**, returning measured evidence for the three gates that
"decide everything" (`02_README` cheapest-path): **G2 quality parity, G3 RAM/doc,
G4 pruning sub-linearity**. No 150M host, no Path-C fork — this is the gate
phase the docs say to run before authorizing any 150M spend.

All three gates run against the **already-stored** SPLADE `sparse_field`
(`data/thinclient_index/spool_backup/med_bio/slice_*.jsonl.zst`) — **no
re-encode**. Source-of-truth chain: `docs/seismic_150m_testbed/` (canonical
for this work) → `03_BENCHMARK_METHODOLOGY.md` (metrics→script→result-file
ledger) → `06_FINDINGS.md` (numbers land here).

## Verified facts that shape the plan

- `pyseismic-lsr` 0.5.0 IS in the `.venv`; `import seismic` works. Native jsonl
  build format = `{"id": <int|str>, "vector": {token: weight}}`. Search =
  `idx.search(query_id, np.array(tokens, dtype=seismic.get_seismic_string()),
  np.array(values, dtype=np.float32), k, query_cut, heap_factor)` →
  `[(query_id, score, doc_id), ...]`. `SeismicIndexLV` = large-vocab variant
  (>65K tokens — our SPLADE vocab qualifies; decide at P1 build).
- `idx.print_space_usage_byte()` prints a byte breakdown (**Forward Index** vs
  **Posting Lists** = packed_postings + block_offsets + summaries vs Knn) —
  this is the G3 forward-vs-inverted/summary split the gate asks for, built in.
- `nightly-x86_64-unknown-linux-gnu` toolchain IS installed (rustup) → the
  instrumented Rust rebuild for G4 is buildable here, no network toolchain fetch.
- `iter_slice(path)` (`scripts/build_thinclient_index.py:205`) streams a
  zst slice line-by-line yielding full doc dicts incl. `sparse_field` — the
  spool→SEISMIC-jsonl converter reuses this; `--limit N` reproduces the BMP
  0.93M vs 2.0M split exactly.
- BMP probe templates to mirror (`spike/mmap_bmp/`): `measure_p3b_pruning.py`
  (G4 `blocks_scored/num_blocks` shape), `measure_p3a_inverted_floor.py`
  (`rssanon_gb()` + `del`+`gc.collect()` load-before/after — G3 RAM lens),
  `measure_qdrant_floor.py` (`_status_kv()` /proc pattern).
- `encode_splade(text, model_path) -> dict[str,float]` (`src/lib/opensearch_retriever.py:157`)
  is the query encoder; `models/splade_onnx_fp16` is the model path.
- The 0.93M + 2.0M BMP persona sub-shards were sourced by `--limit` on the same
  `med_bio` spool; BMP shard docs confirmed 929K vs 2.0M (`splade_000=2.0M`,
  `splade_001=0.93M`, …). SEISMIC pair will read the SAME spool with the SAME
  limits → directly comparable to the BMP probe.

## G4 instrumentation decision (user-confirmed)

FOSS `seismic` exposes **no per-query candidate/block counter** — `search()`
returns only top-k (verified against `src/inverted_index.rs::search` + the
wrapper). The `visited: FxHashSet` (candidates scored) and the per-block loop
in `posting_list.rs::search/sort_and_search` are Rust-local and not bound.

**Chosen: Rust-source patch + local rebuild.** Clone upstream `TusKANNy/seismic`
at the 0.5.0 tag, add a binding `search_with_stats()` that returns
`(results, n_candidates)` where `n_candidates = visited.len()` — the faithful
surrogate for BMP's `blocks_scored` (the docs' G4 metric is literally
"candidates_scored / corpus"). Rebuild the wheel with maturin into a
**separate throwaway venv** (per `04_BUILD_AND_GATHER.md`: "NOT the serving
.venv, source-only wheels"). Tag the fork clearly as an instrumentation fork
and record that R-OBSOLETE (upstream may ship its own on-disk mode) means we
re-check before Path C.

Fallback built into the script: if the rebuild is blocked, the G4 probe still
runs in **recall-vs-bruteforce proxy** mode (recall@k vs exact dot-product at
both corpus sizes; high+stable recall with constant query_cut = pruning works)
so the gate is never silently empty — it's just labeled "proxy" in the ledger.

## Deliverables (each its own commit, staged explicitly — never `git add .`)

All scripts land in `scripts/seismic_testbed/`. All results →
`data/eval_results/seismic_*`. Every result file commit also updates
`06_FINDINGS.md` in the same commit (doc-freshness rule).

### P1 — persona SEISMIC build (G1)
1. **`scripts/seismic_testbed/spool_to_seismic_jsonl.py`** — stream
   `spool_backup/med_bio/slice_*.jsonl.zst` via `iter_slice`, emit
   `{"id": openalex_id, "vector": sparse_field}` jsonl (NO re-encode; pass the
   stored `{token: float}` through unchanged; `id` as the OA string id).
   `--limit N` reproduces the 0.93M/2.0M splits. Writes to an external ext4
   dir (NOT serving `data/`), mirroring `build_persona_bmp.py`'s isolation.
2. **`scripts/seismic_testbed/build_persona_seismic.py`** —
   `SeismicIndex.build(jsonl_path, …)` (or `SeismicIndexLV.build` if vocab
   >65K; auto-detect from the jsonl), param-match Qdrant recall@k FIRST
   (R-PARAM: lock n_postings/centroid_fraction/summary_energy/query_cut to the
   Qdrant-recall-matching point, never to the latency-flattering point).
   `idx.save(path)`. Logs build time, peak build RAM (watch MemAvailable — the
   R-BUILD150M projection starts here, even at persona). Record on-disk size.
   → **G1 PASS check: index builds, no OOM.**

### P2-G2 — quality parity
3. **`scripts/seismic_testbed/seismic_backend.py`** — small lib: load a saved
   SEISMIC index once per process, expose `search(query_text, top_k) ->
   [(oaid, score)]` using `encode_splade` + `get_seismic_string()`. Token
   strings (not bert-vocab-ints) so it's independent of the Qdrant ingest path.
4. **`scripts/seismic_testbed/eval_seismic_parity.py`** — reuse the 34-common
   / 120-query set + the `eval_thinclient_parity.py` query loader +
   `ndcg_at_k`/overlap helpers. Compute **overlap@10 vs Qdrant** (B1, ≥0.95)
   and per-leg NDCG@10 on the SAME vectors. Head-to-head vs the Qdrant
   baseline (live on :6333, `splade_par30` collection — the A1 structural
   control). → `seismic_parity_persona_<ts>.json`. → updates `06_FINDINGS`.

### P2-G3 — RAM floor (forward vs inverted/summary)
5. **`scripts/seismic_testbed/measure_seismic_ram.py`** — mirror
   `measure_p3a_inverted_floor.py`: baseline RssAnon + Pss_Anon
   (`/proc/self/status` + `smaps_rollup`), `load()` the saved persona index,
   `gc.collect()`, re-measure → resident delta = Path-A floor. **Then** parse
   `print_space_usage_byte()` output to split forward-index vs
   inverted/block/summary bytes → answers G3's explicit
   forward-vs-inverted-question. Per-doc rate + 150M projection. Compare to
   Qdrant's 43 B/pt / 6.55 GB@150M. → `seismic_ram_floor_<ts>.json`.

### P2-G4 — pruning sub-linearity (the decisive gate)
6. **`spike/seismic_instrumented/`** — upstream clone + `search_with_stats()`
   patch + maturin build into a throwaway venv. `README` records the fork
   commit/tag + R-OBSOLETE re-check note.
7. **`scripts/seismic_testbed/measure_seismic_pruning.py`** — mirror
   `measure_p3b_pruning.py`: build SEISMIC on the **0.93M** and **2.0M**
   med_bio sub-shards (same queries, same corpus split as BMP), run the query
   set via `search_with_stats()`, record `n_candidates / corpus` per query,
   p50/p95/max. **PASS = ratio FALLS as corpus grows** (BMP failed at ~0.95
   stable). Falls back to recall-vs-bruteforce proxy if the instrumented
   wheel is unavailable (labeled "proxy"). → `seismic_pruning_<ts>.json`.

### Session-end doc sync (its own commit)
8. Re-read `06_FINDINGS.md` + `02_GO_NO_GO_GATES.md` Measured column against
   what shipped; fill the Measured cells (G1/G2/G3/G4) with absolute-date
   values + result-file paths. If any gate fails, set the explicit NO-GO
   branch per `02` kill criteria. Update `docs/README.md` index if docs move.

## Calcium / guardrails
- **No blanket add.** `git status --short` → stage only the scripts/docs I
  edited, commit, push. Result JSONs are committed in their own commits (they
  are small, under `data/eval_results/`).
- **Throwaway venv for the instrumented wheel** — leave the serving `.venv`
  untouched.
- **Host RAM is 31.6 GB, ~7 GB free now.** The persona 0.93M/2.0M builds are
  the budget targets; if a build's peak MemAvailable heads under ~2 GB, I stop
  and report rather than OOM-kill the box (mirrors `SFU_LOAD_MEM_FLOOR_GB`).
- **Measured, not flagged.** Every claim in `06_FINDINGS.md` gets the eval
  path + result-file path + absolute date; unmeasured claims marked `est.`
- Scope = persona P1/P2 only. Do NOT touch the 150M collections, do NOT start
  Path C, do NOT reopen the laptop-tier Qdrant question (`00_VISION` non-goals).

## Out of scope (per docs, do not pull forward)
Path C substrate (Lance/memmap2/redb), G5–G9, the 150M build, the build-vs-buy
decision — all downstream of P2 greens. If any of G2/G3/G4 fails, STOP per
`02` kill criteria and document; do not proceed to P3.
