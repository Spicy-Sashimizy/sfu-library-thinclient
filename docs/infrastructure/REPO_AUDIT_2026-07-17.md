# Repo audit — organization, hygiene, git history (2026-07-17)

**Status:** ACTIVE

**Three-agent read-only audit (owner-requested) + the execution plan.
Findings verified with grep/test -e/git evidence by the agents; nothing
moved yet except the SAFE git-branch fixes marked ✅DONE.** Mass moves are
deliberately deferred to a dedicated session (wave-5 GLM was live in this
tree during the audit; the serving stack references on-disk paths).

## 1. Repo root (agent 1)

| Finding | Size | Action |
|---|---|---|
| `4673e9a6-….data` stray blob (not in git) | **508 MB** | DELETE + gitignore pattern |
| `.tools/` (dead Qdrant binary) | 82 MB | DELETE (track killed) |
| `snapshots/` (empty), `.qdrant-initialized`, `_dbg_sk.mjs`, `sym_shape_infer_temp.onnx` | ~230 KB | DELETE + gitignore |
| TRACKED: `tmpclaude-*-cwd` ×2, `desktop.ini`, `claude_desktop_config_fixed.json` | tiny | `git rm` (SAFE — zero refs) |
| TRACKED: `benchmark_optimization_results.json`, `scripts/sweep_interaction_log.txt` | — | `git rm --cached` + gitignore (generated at runtime) |

## 2. scripts/ + spike/ (agent 1)

- Families healthy: `seismic_testbed/` (103, live), `demo_dependability/`
  (17, live), `demo_broker/`, `tests/`, `archive/`.
- Dead-track strays → `scripts/archive/`: `spike_qdrant_sparse.py`,
  `qdrant-serve.supervisor.conf`, `bmp_ingest_watchdog.sh` (NEEDS-REPOINT:
  doc-only references — add dated archive notes in the referencing docs).
- Uncommitted BMP scratch `scripts/_probe_bmp.py`, `_smoke_serving.py`: DELETE.
- ~40 loose `eval_*/benchmark_*` research scripts → group under
  `scripts/experiments/` (NEEDS-REPOINT: verify no conf invokes by path).
- `spike/archive/mmap_bmp/` = killed-track remains, plan-doc refs only → archive.

## 3. data/eval_results (agent 2) — 711 files, 212 MB

- **SAFE archival ≈ 105–110 MB** → `data/eval_results/archive/`:
  `_r3_cachestat_*` (26×3.3 MB), `_r3_cap*_ledger.log`, `_deployprep*`
  scratch, `_e8s2_*` scratch, unreferenced `_e5_*`/`_wi*` logs.
- NEEDS-REPOINT first: 6 `_r3_*` files referenced by
  `session_2026-07-14…/04_CONVERGENCE_ARTIFACT.md`; `_wi13_update_drive4.log`.
- Canonical result JSONs (seismic/q7/g8/e7/benchmark/wi9–14): DO NOT MOVE.
- `.INVALID` tagging: consistent (3 files, all with notes). ✅ clean.

## 4. Docs integrity (agent 2)

- `docs/README.md`: zero broken refs ✅.
- `docs/THIN_CLIENT_SWAP.md`: **7 broken refs** (L272/322/383/397/592/766/809/843
  — `migration-150m.supervisor.conf` [now in scripts/archive/],
  `data/thinclient_1m`, `spool_backup/`, `qdrant-offbmp.supervisor.conf`,
  empty bmp glob). FIX: repoint to `scripts/archive/…` or mark historical.
- Soft-orphans: `seismic_150m_testbed/build_plans/01–04` reachable only via
  nested README — add one line to the main index.

## 5. Git history (agent 3)

- **Mislabeled commits: CLEAN** — 15-commit spot-check of the campaign:
  prefixes match diffs, WI numbers match files, trailers present.
- Orphans: 4 dangling commits = dropped stashes/WIP (low sev); fsck shows
  missing-blob noise → run `git gc` at next quiet point.
- Sync: active branch fully pushed ✅; `archive/bmp-qdrant` was behind 1
  (✅DONE fast-forwarded); `public` has **3 unpushed commits with no
  remote** (portfolio README — owner decision needed: push where, or fold).
- Merged stale branches q1.1–q1.4: ✅DONE deleted locally.

## 6. Branch naming (owner ask) — the plan

| Branch | Verdict | Action |
|---|---|---|
| `spike/mmap-bmp` (ACTIVE, 411 ahead of default) | **Misnamed** — named for a track killed 2026-06-26; carries the SEISMIC mainline + all campaigns | AFTER wave-5 exits: fast-forward default onto it, then retire the name (see below) |
| `sfu-library-thinclient` (default) | Stale (strict ancestor, 0 unique) but the NAME must stay — renaming it would break ClaudeBox configuration | **Fast-forward to head** (zero-risk: pure ancestor), keep as default |
| `spike/mmap-bmp-zerodecode`, `worktree-zerodecode-tiebreaker` | Accurately named spike branches | leave |
| `archive/bmp-qdrant` | Accurately named | ✅ synced |
| q1.1–q1.4 | merged, stale | ✅ deleted |
| `public` | accurately named, un-anchored | owner decision on its remote |

**Post-wave-5 sequence (one supervised session):** (1) `git fetch && git
push origin spike/mmap-bmp:sfu-library-thinclient` (ff the default to the
campaign head); (2) switch working checkout to the default branch; (3)
delete `spike/mmap-bmp` local+remote (its history is fully contained);
(4) execute §1–§3 moves with explicit adds + repoints; (5) `git gc`.
Future line naming: `spike/<track>` for experiments (matches existing
convention), default branch for the mainline.

## Execution status — EXECUTED 2026-07-17 (post-wave-5 session)

- ✅ Branch surgery: default ff'd to campaign head; `spike/mmap-bmp` deleted local+remote; q1.x deleted; archive ff'd.
- ✅ Root: ~591 MB deleted; tracked strays git-rm'd; generated files removed from the index; .gitignore patterns added.
- ✅ scripts/: 7 dead-track → archive/, 25 research → experiments/, spike/mmap_bmp → spike/archive/; all doc+code refs repointed (stale-grep 0).
- ✅ eval_results: 85 files (~107 MB) → archive/ with per-file doc-reference guard (5 cited files kept in place).
- ✅ Docs: spool_backup present-tense refs dated as reclaimed; build_plans indexed; other audit flags judged historical narrative and left.
- ✅ Claude-nav layer: root README, 4 new scoped CLAUDE.md (+ existing thinclient one), eval_results conventions README, .claude/CLAUDE.md 338→166 lines (binding rules verbatim; removed the embedded `git add .` tutorial contradiction; Pommel map → POMMEL_ACCESS.md).
- ✅ `git gc` run.
- Open (owner decisions): `public` branch's 3 unpushed commits; the `.scratch/` gitignored BMP content.
