# Delta layer serving fixes, 2026-10-01 (Agent E, second-wave dispatch)

**Status:** ACTIVE

Scope: serving-side items from `docs/delta_ingest/02_DESIGN.md` §3.1 that
need no index load: the buffer-section-missing-at-load gap, O2, O16, plus an
assessment of O13 and O8. Tests: `scripts/tests/test_delta_serving_fixes.py`
(synthetic roots, built the same way as `test_delta_buffer_refresh.py`).
**EFFICACY: unit-tested only. Serving effect (latency, recall) UNMEASURED.**

Every change is a strict no-op with `SFU_DELTA_ROOT` unset or empty.
`DeltaLayer.load_if_enabled` returns None before any new code runs,
`retriever._delta` stays None, and the one new retriever call site is guarded
by `if self._delta is not None`. Test `test_gate_off_has_no_delta_layer`
covers this.

| Item | Commit | What was wrong | Repro test (failed before the fix) | Fix |
|---|---|---|---|---|
| Buffer section missing at load | e59ad355 | If `<delta>/buffer/delta_buffer/tantivy/meta.json` did not exist when the layer loaded, `section_dirs()` skipped it, `_load` registered no `delta_buffer` section, and BM25F never searched buffered docs until `reload()`. The SPLADE leg was fine after O1. | `test_buffer_section_created_after_load_is_searched`: BM25F returned `set()` for the 3 buffered ids | `DeltaLayer.buffer_section_dir()`; `_bm25f_leg` calls `_delta_attach_buffer_section()`, which does one `stat` per query until the dir appears, then opens it under the load lock with a copy-on-write rebind of `_sections` and re-checks that `_delta` is still the same object |
| O2 | c6a9d4de | `finish_generation` moves frozen records out of the buffer view (gen 0 + `building`) before serving `reload()`s the new generation, so the SPLADE buffer leg, meta and abstracts lost them in that window. Separately, every `building` generation was parsed into the buffer, including a compaction of generations that were already loaded (that is the RAM cost the original one-line fix was rejected for). | `test_frozen_generation_stays_visible_until_reload` (`0 == 3`), `test_unloaded_compaction_of_unloaded_freezes_stays_visible` (`0 == 5`), `test_building_compaction_of_loaded_generation_not_in_buffer` (`3 == 0`) | `_buffer_generations()`: buffer = gen 0 + every `building` or published-not-loaded generation that is *buffer-derived*. That means its ledger `info.from_gens` are all 0 or themselves unloaded and buffer-derived. A published row whose `info` no longer has `from_gens` counts only if no loaded generation is `compacted`, because only a compaction can move loaded docs into a newer generation. A freeze therefore keeps exactly the rows the layer already held (signature unchanged, no re-parse), and a compaction of loaded generations is never parsed. A rebuild is forced when the buffer-generation set loses a member. |
| O16 | 8520e6e2 | The CLI default `<index_root>/delta` lands under `data/thinclient_index` (9p, not to be written casually), and nothing stopped a root inside `data/seismic_150m`. | `test_resolve_delta_root` (new API) | `resolve_delta_root(index_root, value, for_write=False)`: precedence is explicit > `SFU_DELTA_ROOT` > `<index_root>/delta`, and `1` = `<index_root>/delta`. Writers (`for_write=True`) are refused inside `data/seismic_150m` and when the root is implicit and falls under the repo `data/`. Serving resolution is unchanged. **The CLI is not wired yet** (see below). |
| O13 | 6fc81e66 | Code reading suspected a plain-compressed bucket being decoded with the latin dict. | `test_o13_nonlatin_plain_fallback_decodes_with_latin_dict`: forced order, round-trip of 800 docs passes | No code change. The path exists but is **benign**: a frame written without a dict has dictID 0, never references dict content, and decodes identically under any dict. The reverse (dict frame, plain decoder) raises `Dictionary mismatch`. Invariant recorded. |

## Still open / changes needed in the ingest side (owner: spike/delta_ingest)

1. **O16 CLI wiring** (`spike/delta_ingest/cli.py`, the line
   `delta_root = Path(args.delta_root) if args.delta_root else index_root / "delta"`):
   replace it with
   `delta_root = resolve_delta_root(index_root, args.delta_root, for_write=True)`
   (`from lib.thinclient.delta_layer import resolve_delta_root`), and update
   the `--delta-root` help text. Two behaviour changes for writers: the CLI
   then honours `SFU_DELTA_ROOT=<path>`, and an implicit root under `data/`
   exits with the error message.
2. **O2 exactness after a compaction:** `ledger.finish_generation` overwrites
   `generations.info` with `generation.json`, which drops `from_gens`. Keeping
   it (merge `from_gens` into the new info) would let the reader classify
   every published generation exactly. Without it, a freeze published after
   a compaction of a loaded generation is not counted as buffer until
   `reload()`. That residual is pinned by the CODE_INVARIANTS text.
3. **O2 BM25F residual:** `flush` deletes the frozen docs from the buffer
   tantivy right after the freeze, so BM25F misses them until `reload()`.
   The SPLADE leg, meta and abstracts are covered. A fix needs either a
   delayed buffer delete or lazy attachment of unloaded generation sections
   with masks. Design only, not done.

## O8 assessment (not fixed: not serving-side)

- The labels are class attributes in `src/lib/thinclient/doc_encoder.py`:
  `SpladeDocEncoder.backend = "pytorch_fp16"` (line ~92) even on CPU, where
  the model stays fp32, and `SpladeDocEncoderTRT.backend =
  "onnxruntime_trt_iob_fp16"` (~166) even when ORT falls back from TensorRT
  to CUDA (`session.get_providers()` is only logged).
- Fix is small: set `self.backend` per instance, e.g. `pytorch_fp32_cpu` when
  device != cuda, and derive the ORT label from `get_providers()[0]`.
- This is the build/ingest encoder, not the serving path, and results files
  and monthly-rebuild metadata key on these strings, so a rename would change
  provenance strings downstream. That is the owner's call. Not done here.
- No efficacy impact. It is a labelling defect only; numbers measured under
  the wrong label stay valid, but their label should be read as "requested
  backend".

HEAD when the tests last ran: see the commits above (the tests ran on the
working tree with Agent F's uncommitted `cli.py`/`adapters.py` edits present).
