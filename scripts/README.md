# scripts/ — operator entry points and script families

**Status:** ACTIVE

The root of this directory holds only the scripts an operator runs by hand;
everything else lives in a family directory. New scripts go in a family,
never at the root (`CLAUDE.md` here has the rules for agents). Constraints
and gotchas for every script are in `docs/CODE_INVARIANTS_SCRIPTS.md`. Always
run Python through the project venv: `.venv/bin/python3`.

New scripts (2026-10-11 policy, `docs/infrastructure/SCRIPT_HYGIENE_POLICY.md`):
a family directory, and a module docstring with `Lifecycle: operator|library|tool|harness|one-off`
(`harness`/`one-off` also name `Doc:`; `one-off` also names `Results:` and lives only in
`experiments/`). The pre-commit hook and the Claude write guard enforce this; a commit of
≥10 files, ≥500 lines, or any code delete/rename needs `repo_tools/preflight.py run` first.

## Root — operator entry points

| Script | What it does |
|---|---|
| `serve_http.sh` | start the HTTP server (uvicorn, `source/sfu_library_mcp_http.py`) with the documented environment matrix; the GUI is at `/app` |
| `stage_seismic_local.sh` | copy the served SEISMIC shards from the 9p mount to local disk before serving (random page faults are ~0.5 ms over 9p) |
| `build_thinclient_index.py` | build the per-section tantivy indexes + sidecars from the spool (resumable; the source index is gone since 2026-09, kept for the rebuild path) |
| `build_flat_blocks.py` | build the N5 flat abstract sidecar + ordinal locator for a section |
| `snapshot_downloader.py` | OpenAlex snapshot ingest (GPU cuDF, resumable) |
| `run_parity_safe.sh` → `eval_thinclient_parity.py` | the parity oracle: thin-client versus baseline top-K, memory-guarded, one engine per process. Its `record-os` phase needs the decommissioned OpenSearch baseline and cannot re-run (`record-os` and `combined` with a baseline now exit with "OpenSearch baseline decommissioned 2026-06-11", 2026-10-11); the BMP-era shard-wave recorder `eval_parity_section_waves.py` moved to `archive/bmp_era/` 2026-10-11 |
| `prime_result_cache.py` | re-prime a RUNNING serve's result cache over HTTP |
| `sweep_stray_tantivy_files.py` | remove tantivy segment files a section's metadata does not reference |
| `setup_cloudflare_mcp.sh` | Cloudflare tunnel / WAF / DNS for remote MCP access (`docs/infrastructure/REMOTE_MCP_ACCESS.md`) |
| `build_web.mjs`, `verify_web_jsdom.mjs`, `verify_web_progress.mjs`, `e2e_sweep.mjs` | compile the GUI's JSX and run the headless / Playwright checks (`web/README.md`) |

## Families

| Directory | What | Docs |
|---|---|---|
| `seismic_testbed/` | SEISMIC research drivers (e/g/f/q-series, builds, benches, judges). Active evidence harnesses — keep as pinned | `docs/seismic_150m_testbed/` |
| `experiments/` | research evals and benchmark harnesses, including the delta-ingest fold-in evals. Superseded-but-cited: never delete, docs cite these paths | `docs/BENCHMARK_METHODOLOGY.md`, `docs/delta_ingest/` |
| `tests/` | the `scripts` half of the pytest suite (46 files; the other half is `source/tests/`) | `pytest.ini` |
| `demo_broker/` | the public OCI demo broker (landing page, invite links, wake/stop, caps). DEPLOYED — reopened 2026-10-06; the running copy is on the broker box | `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` |
| `gui_testbed/` | Playwright + axe + gremlins GUI interaction testbed (WI-16) | `docs/infrastructure/GUI_INTERACTION_TESTBED_PLAN.md` |
| `portable_socsci/` | builds the portable social-sciences Windows bundle | `docs/infrastructure/PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` |
| `portable_linux/` | builds the relocatable Linux runtime bundle | `docs/infrastructure/PORTABLE_LINUX_BUNDLE.md` |
| `reproduce/` | the outsider's path: rebuild a servable index from the public OpenAlex snapshot and verify it serves (`rebuild_from_openalex.py`, `verify_rebuild.py`) | `docs/REPRODUCIBILITY.md` |
| `repo_tools/` | repository maintenance: `check_script_placement.py` (placement + lifecycle policy), `symbol_inventory.py` (function/class inventory + diff versus a tag), `preflight.py` (restore tag + tests + inventory before a substantial commit), `triage_audit.py` (re-derives the 2026-10-11 triage ledgers' DEAD/MISPLACED claims from git), `hooks/pre-commit` + `install_git_hooks.sh` (tracked git hook), `build_eval_results_index.py` (regenerates `data/eval_results/INDEX.md`) | `docs/infrastructure/SCRIPT_HYGIENE_POLICY.md`, `docs/infrastructure/REPO_REORG_2026-10-10.md` |
| `data/` | `demo_payload_manifest.json`, the 2026-08-19 payload snapshot (paths as they were that day) | `docs/deprecated/oci_demo/` |
| `archive/` | dead-track code kept as evidence: BMP/Qdrant/migration era, `demo_dependability/`, `inplace_update/`. Never delete, never resurrect without a decision record | `docs/README.md` §Closed tracks |
