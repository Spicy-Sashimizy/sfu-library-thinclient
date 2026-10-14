# Script triage 2026-10-11 — ledger, decisions, applied changes

**Status:** ACTIVE

**What this is.** The record of the 2026-10-11 line-by-line triage of every tracked
file under `scripts/` (402 at the start), done because the owner asked that each
script be either confirmed active, moved to its proper family, or, when confirmed
one-time-use and dead, deleted — with recovery guaranteed and nothing working
changed. Method and class vocabulary: `SCRIPT_HYGIENE_POLICY.md` §5. Division of
labour (owner instruction): five **Opus** agents read and classified (one row
per file, evidence per row); every
general audit ran on **Fable** — `scripts/repo_tools/triage_audit.py` re-derived
each DEAD and MISPLACED claim from git, the REVIEW rows were settled from the
code and docs, and every applied commit went through the preflight gate
(restore tag + 681 tests + function inventory).

## Restore point and checks

The state before the whole 2026-10-11 wave is the restore tag
`pre-rust-core-and-script-triage-2026-10-11`, kept by the owner (verified by a
detached checkout before any change: 2,525 files, tests pass, serve path
imports, 5,332 symbols). Each commit below is self-contained; the moves table
below or `git log --follow --oneline -- <new path>` says where a file went.
Nothing working changed: `symbol_inventory.py diff` reports 0 protected and 0
evidence removals at every commit (shell wrappers are not Python symbols; the
three deleted files were shell); `src/tests` 669/669 and the policy tests 12/12
at every commit; `scripts/tests/test_demo_payload_manifest.py` 13/13 after its
subject moved.

## Commits (all through `preflight.py run`)

| # | Commit | What |
|---|---|---|
| 1 | f37afa78 | audit-tool fixes (20-line banner read, token regex); one hook installer (`install_git_hooks.sh` installs both tracked hooks; duplicate `install_hooks.sh` removed) |
| 2 | c4a6ead7 | 12 files moved (7 MISPLACED decisions), every path reference repointed, depth-dependent repository roots fixed in each moved file, `Lifecycle: tool` added to the vocabulary |
| 3 | 50479654 | CLOSED banners on 36 archive files |
| 4 | 94ff0367 | 3 confirmed-dead shell wrappers deleted; §5 policy refinement for archive clutter |
| 5 | this commit | this ledger, docs index rows, the per-language dictionary measurement recorded in `LEXICAL_STORAGE_RESEARCH.md` §7.3, ledger rows repointed to post-move paths |

## Result

| Class (final) | Files | Note |
|---|---|---|
| ACTIVE | 138 | serving/build/deploy paths, operator entry points, live tests, the two files the triage itself added |
| HARNESS (cited) | 189 | re-runnable evals a doc cites; stay in `experiments/` and `seismic_testbed/` |
| ONE-OFF (recorded) | 53 | +1 settled: `eval_per_language_dicts.py` (results existed, doc did not cite them; §7.3 now does) |
| MISPLACED → moved | 12 files | table below |
| DEAD → deleted | 3 | table below |
| REVIEW → settled | 16 → 0 open | table below; 14 rows keep the REVIEW label in the agents' ledgers as their record, each settled here |

Audit: coverage 400 tracked / 400 ledgered (+4 DELETED rows: the three files below and the folded hook installer), 0 DEAD failures, 0 archive files
without a banner, 0 duplicates.

### Moves (git mv, basenames kept; commit c4a6ead7)

| From | To | Why | Repointed |
|---|---|---|---|
| `scripts/seismic_testbed/kimi_vs_haiku_rebake.py` | `scripts/experiments/` | `import benchmark_llm_judge` broken since that module moved 2026-07-17 | usage string; `Lifecycle: harness` added |
| `scripts/experiments/eval_speculation_playwright.mjs` | `scripts/gui_testbed/` | imports `gui_testbed/lib.mjs` | import path; `REPO_REORG_2026-10-10.md` note |
| `scripts/experiments/eval_qdrant_uint8_sparse_small.py`, `scripts/tests/test_qdrant_uint8_sparse.py` | `scripts/archive/qdrant_uint8_sparse/` | track CLOSED SUPERSEDED 2026-09-25; the test leaves the suite with its subject | test `_SRC` + root depth; `docs/archive/qdrant_uint8_sparse/README.md` |
| `scripts/experiments/{benchmark_topic_export, eval_splade_finetune_subset, prune_topk_experiment, benchmark_splade_optimizations}.py` | `scripts/archive/opensearch_era/` (+ README) | first three import the removed OpenSearch client; fourth is an encoder-throughput benchmark with no tracked result; no live doc cites any | root depth in all four (they had computed the wrong root since 2026-10-10) |
| `scripts/seismic_testbed/sml_host_orchestrator.sh` | `scripts/archive/smallmachine_levers/` | track CLOSED DEAD 2026-09-25 | usage path |
| `scripts/eval_parity_section_waves.py` | `scripts/archive/bmp_era/` | BMP shard-wave recorder; BMP artifacts deleted 2026-06-25, SEISMIC promoted 2026-07-06; its numbers stay cited | 9 files (`BENCHMARK_METHODOLOGY`, `STORAGE_BUDGET_150M`, `THIN_CLIENT_SWAP`, two `bmp_decommission_plan` docs, `eval_thinclient_parity.py` strings, `build_presentation_metrics.py` strings); removed from the root allowlist + README table |
| `scripts/archive/demo_dependability/{build_demo_payload_manifest.py, seed_oci_volume.sh}` | `scripts/demo_broker/` | live upload procedure of the OCI track reopened 2026-10-06; a live test imports the first. **Overrides** the demo_broker/tests ledger's proposal to archive that test instead | test docstring + `sys.path`; `OCI_DEMO_DEPLOYMENT.md`; `CODE_INVARIANTS_SCRIPTS.md` note; `seed_demo_volume.sh` comments; `seed_oci_volume.sh` `BUILDER` path + `../..`; `Lifecycle: tool` added |

Left where they are on purpose: `scripts/data/demo_payload_manifest.json` (dated
2026-08-19 snapshot; its paths are as they were that day) and the `eval_script`
strings inside `data/eval_results/*.json` (records of past runs).

### Deletions (commit 94ff0367; all five DEAD conditions re-derived by the audit)

| Path | Last commit | Evidence |
|---|---|---|
| `scripts/seismic_testbed/t23c_host_orchestrator.sh` | 1a3bbf95 (2026-09-02) | AMEND1 t23c descent wrapper; track CLOSED-UNRUNNABLE 2026-09-25; no `t23c_*` results; passes `--t23c descent`, which the driver does not accept |
| `scripts/archive/azure_indexer.sh` | 74710452 | OpenSearch-era Azure SPLADE indexing recipe; calls `scripts/splade_indexer.py`, which no longer exists; no run recorded; 0 references |
| `scripts/archive/parallel_cpu_indexer.sh` | 74710452 | companion of the above (its only reference was `azure_indexer.sh`) |

### REVIEW rows and how each was settled (Fable)

| Row | Settled as | Basis |
|---|---|---|
| `scripts/tests/__init__.py` | ACTIVE, keep | both suite halves carry a package marker; no shared test basenames; harmless under `--import-mode=importlib` |
| `scripts/tests/test_qdrant_uint8_sparse.py` | moved with its subject | see moves |
| `scripts/tests/test_demo_payload_manifest.py` (MISPLACED proposal) | ACTIVE, keep | its subject is the live upload procedure; subject moved to `demo_broker/` instead |
| `scripts/seismic_testbed/f3_pin_ab.py` | HARNESS (deferred track), keep | disk-streaming track is DEFERRED 2026-09-25, not closed; no deletion while a track can reopen |
| `scripts/experiments/arxiv_fetcher.py` | HARNESS, keep | `EXTERNAL_API_CONTRACT.md` and `delta_ingest/02_DESIGN.md` name it; its stale `parent.parent` root is noted, not changed (evidence harness) |
| `scripts/experiments/eval_per_language_dicts.py` | ONE-OFF (recorded) | results existed; `LEXICAL_STORAGE_RESEARCH.md` §7.3 now records them |
| `scripts/experiments/{benchmark_topic_export, eval_splade_finetune_subset, prune_topk_experiment, benchmark_splade_optimizations}.py` | moved to `archive/opensearch_era/` | see moves |
| `scripts/run_parity_safe.sh` | ACTIVE, keep | root operator entry point cited by `REPRODUCIBILITY.md`; its `record-os` phase needs the decommissioned OpenSearch baseline and cannot re-run (README row says so now) |
| `scripts/archive/azure_indexer.sh`, `parallel_cpu_indexer.sh` | deleted | see deletions |
| `scripts/archive/demo_dependability/__init__.py` | keep, bannered | empty package marker; harmless |
| `scripts/archive/demo_dependability/build_demo_payload_manifest.py`, `seed_oci_volume.sh` | moved to `demo_broker/` | see moves |
| `scripts/repo_tools/install_git_hooks.sh` | ACTIVE, now the single installer | installs both tracked hooks; the 2026-10-11 duplicate was removed |

### Not done (by design)

- No `Lifecycle:` header retro-fit on the 380-odd grandfathered scripts; the
  header is required only for new files (`SCRIPT_HYGIENE_POLICY.md` §2) and the
  agents' proposed values are in the ledgers if a retro-fit is ever wanted.
- `spike/` (247 files) was not in scope; it is evidence by policy and gets its
  own wave if the owner asks.
- `scripts/tests/` was not re-run as a whole here (3 GB RSS guard on
  `test_delta_*` in one process, `REPO_REORG_2026-10-10.md` §5); the files the
  triage touched were run individually.
