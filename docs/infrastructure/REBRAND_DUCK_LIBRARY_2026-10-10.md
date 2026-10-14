# Rebrand "SFU Library" → "Duck Library" — ledger, aliases, rollback (2026-10-10)

**Status:** ACTIVE

Scope: everything a demo audience can see (web GUI, MCP tool surface,
installer, broker pages, docs prose) says **Duck Library**. Load-bearing
identifiers (environment variables, module/file names, paths, unit/container names, the
repository, branch and MCP server name) still say `sfu`; each one is listed below
with the reason and what renaming it would take. The GUI-only rebrand
before this one: 2026-08-21 (`4c7ec0c`, `8ac7ba1`, recorded in
`OCI_DEMO_DEPLOYMENT.md`).

## 1. Rollback point

- Restore tag **`pre-rebrand-2026-10-10`** (HEAD before the first rebrand
  commit), kept by the owner.
- Test baseline on that tag (2026-10-10, full `pytest`, one process):
  **1,107 passed / 25 failed / 2 errors**, 236 s. All 27 non-passes are the
  delta-ingest tests that trip the RSS memory guard when the suite runs in
  one process (`test_delta_abs_route` 2 errors; `test_delta_bm25f_freeze_window`
  5, `test_delta_buffer_refresh` 2, `test_delta_generation_paths` 4,
  `test_delta_ingest` 1, `test_delta_ingest_layout_cadence` 9,
  `test_delta_serving_fixes` 4 failures) — the same set the reorg ledger
  `REPO_REORG_2026-10-10.md` recorded.

## 2. Commits and how to revert each

| # | Commit | What changed | `git revert <sha>` safe alone? |
|---|---|---|---|
| 1 | `ed2ce623` | MCP surface: tool descriptions/outputs, tools renamed to `browse_library_databases` / `check_library_access` + legacy-name aliases, `format_library_*` + `format_sfu_*` aliases, Zotero `Duck-Library-RecordID` tag, entry-point docstrings, HTTP start-up banner; tests; CODE_INVARIANTS + THIN_CLIENT_SWAP | Yes. |
| 2 | `ac7aacdf` | Web GUI: mock access labels, admin e-mail placeholder, Index Manager env-gate labels, headings, rebuilt `web/*.js`, `?v=duck6`→`?v=duck7` | Yes. Rotate the token again (`duck8`) after reverting so browsers and edge caches drop the duck7 assets. |
| 3 | `547273fb` | Demo broker (architecture page model labels, ntfy title, README, systemd `Description=`), portable Windows installer text/shortcut/default folder, launcher and deploy/ banners, portable seed CLAUDE.md, OCI_DEMO_DEPLOYMENT entry | Yes. |
| 4 | `af696081` | Docs prose (GUI_REFERENCE, REMOTE_MCP_ACCESS, LOCALIZED_DEPLOYMENT_PLAN, 11_EXPERIMENT_BACKLOG, root README note) | Yes. |
| 5 | (this ledger commit) | This doc + `docs/README.md` / `infrastructure/README.md` rows | Yes, but revert it last — it is the record of 1–4. |

## 3. Compatibility aliases

| Old name | New name | Where the shim lives | Removable when |
|---|---|---|---|
| MCP tool `browse_sfu_databases` | `browse_library_databases` | `src/lib/tools.py` `_dispatch_tool` dispatch dict (old key, same handler; not in `TOOL_DEFINITIONS`) | No client configuration, script or saved prompt calls the old name (check MCP metrics logs for the name) |
| MCP tool `check_sfu_access` | `check_library_access` | same | same |
| `formatters.format_sfu_database` | `format_library_database` | module-level alias at the end of `src/lib/formatters.py` | `git grep format_sfu_` is empty outside the alias — **removed 2026-10-11** (codebase triage; condition met) |
| `formatters.format_sfu_databases_list` | `format_library_databases_list` | same | same — **removed 2026-10-11** (codebase triage; condition met) |

All four are recorded in `docs/CODE_INVARIANTS.md` §"src/ MCP entrypoints &
misc"; `test_tools_unit.py` pins the tool aliases (alias dispatch + legacy names
not advertised). No environment var, module, file or
path was renamed, so no env-var fallback or import re-export was needed.

## 4. Full rollback

- **Preferred (keeps history):**
  `git revert --no-edit <ledger-sha> af696081 547273fb ac7aacdf ed2ce623`
  (newest first), then `git push`.
- **After either:**
  - MCP stdio server: restart Claude Desktop (or close/reopen the
    conversation) so it re-spawns `src/sfu_library_mcp_server.py`.
  - HTTP server + web GUI: restart `scripts/serve_http.sh` (or the
    supervisor/systemd unit `sfu-serve`); run `node scripts/build_web.mjs`
    and rotate `?v=duckN` in the four `web/*.html` files.
  - Broker box (if redeployed): copy `scripts/demo_broker/` back,
    `sudo systemctl daemon-reload && sudo systemctl restart sfu-broker`.

## 5. Verification checklist (results 2026-10-10)

- [x] Full pytest after commits 1–4: **1,110 passed / 25 failed / 2 errors**
      (191 s; +3 = the new alias/tag tests). The 27 non-passes are
      **identical** to the §1 baseline set (diffed by test id).
- [x] MCP stdio server starts: `initialize` → `{name: "sfu-library", version: 1.26.0}`,
      `tools/list` → 27 tools incl. `browse_library_databases`,
      `check_library_access`; 0 descriptions contain "SFU".
      *(2026-10-12: the surface is now 18 tools after the owner-decision trim;
      see `THIN_CLIENT_SWAP.md` "Full MCP tool surface". The two legacy aliases
      still dispatch.)*
- [x] Tool/HTTP/Zotero/formatter subset: 176 passed.
- [x] Web: `node scripts/build_web.mjs` (3 apps), `verify_web_jsdom.mjs`
      74/0, `verify_web_progress.mjs` 18/0 (one of five runs 17/1, a timing
      flake that did not reproduce).
- [x] Broker tests: 110 passed.
- [ ] Not run here: Playwright `scripts/e2e_sweep.mjs` (no browsers in this
      container), a live HTTP server start, the Windows installer on
      Windows, a broker redeploy.
- [x] Grep: `git grep -in sfu` outside `data/eval_results`, `archive/`,
      `deprecated/`, `scripts/experiments/`, `scripts/seismic_testbed/`
      returns only the categories in §6.

## 6. Inventory — what still says `sfu` and why

Counts are tracked-file hits on 2026-10-10 after commits 1–4, excluding
`data/eval_results/`.

**(a) Branding prose — rebranded** in commits 1–4; nothing user-visible left
in `web/`, the MCP tool list/outputs, the Windows installer, the broker
pages, or active-doc prose.

**(b) Load-bearing identifiers — kept on purpose:**

| Kind | Examples | Hits | What renaming would take |
|---|---|---|---|
| Environment gates | `SFU_SPLADE_BACKEND`, `SFU_DELTA_ROOT`, … (220 distinct) | ~2,900 | A start-up shim that copies `DUCK_*` into `SFU_*` when unset, then a doc sweep of ENV_GATES and every doc/harness; operator `.env`/systemd/compose files on deployed hosts. Not visible to a demo audience. |
| Entry-point modules + logger | `src/sfu_library_mcp_server.py`, `sfu_library_mcp_http.py`, logger `sfu_library_mcp` | ~160 | Client configs/launchers, `serve_http.sh`, supervisor/systemd, Dockerfile, portable bundles all name the files; would need wrapper modules under the old names. |
| MCP server name | `Server("sfu-library")` | 2 | Owner decision (CODE_INVARIANTS: pinned by client configs/launchers). Shown by some MCP clients in the `initialize` result. One-line change in each entry point; cannot be aliased. |
| Model directories | `models/sfu-academic-embed-v5`, `sfu-cross-encoder-v1*`, `sfu-splade-*` | ~230 | Rename on disk on every host + code defaults + eval provenance. |
| Data/query files | `data/sfu_eval_queries.json`, `sfu_training_triplets.jsonl`, `sfu_databases.py` | ~180 | Cited by docs and evidence harnesses by path. |
| Web code identifiers | `window.SFUApi/SFUUI/SFUHistory/SFUMock`, `sfu-*` DOM ids/test ids, localStorage keys, `sfu_proxy` access types | ~360 | Renaming the localStorage keys resets every user's saved prefs/history; the rest breaks the jsdom/Playwright harnesses. Only visible in browser development tools. |
| Units, containers, cloud resources | `sfu-serve/broker/watchdog/rebuild-trigger` units, `sfu-ntfy`, OCI `SFU-thin-serverhosted-150M`, ntfy topic `sfu-truenas-*` | ~170 | Change on the live hosts in lockstep with the repo. |
| Windows bundle internals | `sfu_runtime.cfg`, `sfu-python`, `sfu_bundle.pth` | few | Existing USB installs read these names. |
| Livedocs file magic | `b"SFULIV01"` | 2 | Changing it invalidates every built livedocs file. |
| External SFU services the code really calls | `databases.lib.sfu.ca` Solr, `proxy.lib.sfu.ca` EZProxy | ~90 | These are the actual data sources behind `browse_library_databases`/`check_library_access`/full-text links; renaming would break them. Docstrings that describe them still say "SFU Database Registry". |
| Outbound User-Agent | `SFULibraryMCP/1.0 (mailto:<contact>)` (openalex.py), `SFULibraryMCP/1.0` (semantic_scholar.py) | 2 | **Owner decision:** the product token is sent to OpenAlex/S2 and not seen by a demo audience; the mailto contact is the operator's own (`OPENALEX_MAILTO`; unset means no contact). |

**(c) Provenance / evidence — never edited:**
`data/eval_results/` (453 files, ~6,400 hits); `docs/archive/` (32 files),
`docs/deprecated/` (16), `scripts/archive/` (43), `spike/archive/` (22),
`scripts/experiments/` (71), `scripts/seismic_testbed/` (87) — paths and
pre-registered bars are cited at pinned commits. Active-doc wording that
names the datasets behind measured numbers ("120 SFU eval queries",
"49 SFU subjects", "SFU fine-tunes") is also left as recorded.

## 7. Remaining SFU exposure that needs an owner decision

| Item | Exposure | What renaming would take |
|---|---|---|
| GitHub repository `Spicy-Sashimizy/sfu-library-thinclient` | Visible in any clone URL/link | GitHub rename (old URL redirects), then `git remote set-url` on every clone, and every doc/script naming the repository |
| Default branch `sfu-library-thinclient` | Visible in links/PRs | New branch + set default on GitHub + update CLAUDE.md; tracking branches on all clones |
| Directory `/workspaces/sfu-library-thinclient` | In ~480 paths (venv shebangs, docs, harnesses, devcontainer) | Devcontainer rename + venv rebuild (absolute shebangs) + path sweep |
| MCP server name `"sfu-library"` | `initialize` result | §6(b) |
| Outbound User-Agent product token | OpenAlex/S2 request logs | §6(b) |
| `data/eval_results/` provenance | Paths inside 453 result files | Never — evidence |
| Owner's uncommitted `.devcontainer/*` + `docker-compose.pommel.yml` | Not inspected for branding, not staged | Owner reviews/commits their own edits |
| `docs/archive/`, `docs/deprecated/`, `.claude/plans/` | Historical prose ("SFU Library", tool names) | Low value; would blur the record |
| Root README disclaimer | Says the project is not affiliated with Simon Fraser University and that `sfu` identifiers are historical | Kept on purpose — an honest statement for an SFU-affiliated audience |
| Deployed broker copy | Still serves the pre-rebrand architecture page until redeployed | Redeploy `scripts/demo_broker/` + `daemon-reload` |
| Portable installs made before 2026-10-10 | Folder `SFU-Library`, shortcut `SFU Library.lnk` | Rebuild the bundle; old installs keep their names |
