# Plan — Seismic-only dev container + BMP/Qdrant archival container split (2026-07-06)

> **SUPERSEDED (2026-07-06, same day):** promoted into the docs tree as
> `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md` (adds the full interaction map + Phase A
> completion status — the SEISMIC default flip shipped). Read that instead.

**Goal.** (1) Clear this dev container down to the promoted Seismic search line +
the serving stack it needs. (2) Move the BMP and Qdrant lines into a separate
archival ClaudeBox container for testing/forensics. (3) Keep the SPLADE db (the
Qdrant `splade_150m` collection) accessible to the new container — and from
here, if we ever need cross-checks.

**Answers to the three feasibility questions up front:** all three are YES, with
one architecture decision attached (Phase 3) and two data-retention decisions
(Phase 5).

---

## 0. Measured inventory (2026-07-06, `du -sh`)

| Path | Size | Line | Disposition |
|---|---|---|---|
| `data/seismic_150m/` (dv shards ~32 GB + f16 twins) | 103 GB | **Seismic** | KEEP — f16 twins are the parity reference (doc 12 §5: "do not delete") |
| `spike/seismic_upstream/` + `spike/vectorium_fork/` | 9.5 GB | **Seismic** | KEEP (c1a bin, dv encoder/kernel) |
| `data/thinclient_index/sections/` (tantivy+abstracts) | 42 GB | serving stack | KEEP — lexical leg, not "another project" |
| `data/thinclient_index/meta.sqlite` | 24 GB | serving stack | KEEP |
| `data/thinclient_index/packed/` | 42 GB | serving stack | KEEP (hot/cold deploy artifact) — verify no BMP-era shards inside the tars first |
| `data/thinclient_index/dense/` | 341 MB | serving stack | KEEP |
| `models/` (SPLADE ONNX encoder etc.) | 15 GB | serving stack | KEEP — Seismic leg uses the same encoder |
| `data/qdrant_spike/` (storage = `splade_150m`) | 202 GB | **Qdrant** | MOVE to archive container (Phase 2) |
| `.tools/qdrant/` binary | 82 MB | **Qdrant** | COPY to archive |
| `data/thinclient_1m/` (1M-scale BMP sections — the only .bmp files left) | 2.3 GB | **BMP** | MOVE to archive |
| `data/thin_client_poc/` | 962 MB | **BMP-era** | MOVE to archive |
| `spike/mmap_bmp/` | 9.8 GB | **BMP** | MOVE to archive |
| `data/thinclient_index/spool_backup/` (5 section spools) | 123 GB | build source | **DECISION A** (§5) |
| `data/openalex_snapshot/` (download/indexer checkpoints) | 55 GB | build source | **DECISION B** (§5) |
| `data/dense_compression/`, `data/sectioned/`, `data/thinclient_test_resume/` | ~5.2 GB | research runs | move to archive or delete after result-JSONs confirmed committed |
| `tmpclaude-*/`, `.handoff_extract/`, `sfu library mcp-handoff.zip` | <1 GB | junk | DELETE |

Full 150M .bmp artifacts were already deleted 2026-06-25
(`bmp_artifacts_deleted_manifest_20260625.json`) — "BMP" today is code paths,
docs, the 1M testbed artifacts, and `spike/mmap_bmp`.

Post-split dev container: ~236 GB (Seismic + serving stack). Freed/moved out:
~390 GB. Host C: has 471 GB free — enough to stage the copy before deletes.

## 1. Phase 1 — archival container + git branching (cheap, do first)

1. Create ClaudeBox project `sfu-library-archive` (gets its own container,
   venv, Pommel port per the standard mapping).
2. In this repo: `git branch archive/bmp-qdrant` from the current
   `spike/mmap-bmp` HEAD and push it. **No code deletion needed to "branch
   off"** — BMP/Qdrant code is small and lives in git history; the archive
   container clones the repo and checks out `archive/bmp-qdrant`, the dev
   container keeps working on `spike/mmap-bmp` → main line.
3. Archive container setup: venv per house rules, copy `.tools/qdrant/`,
   `pip install qdrant-client`, copy `models/splade_onnx_fp16` (15 GB — needed
   to encode queries for BMP/Qdrant testing).

## 2. Phase 2 — move the Qdrant storage (the 202 GB)

1. Stop Qdrant cleanly in the dev container (`curl -X POST
   localhost:6333/... ` optional snapshot; then kill the `.tools/qdrant/qdrant`
   process; also disable `scripts/bmp_ingest_watchdog.sh` if scheduled — it
   auto-restarts Qdrant).
2. **Do the move from the WSL2 host / Windows side, not inside the container.**
   Both project workspaces live on the same C: volume; a host-side move is a
   rename (seconds). An in-container `mv` across the two drvfs mounts is a
   202 GB copy (hours).
3. Move `data/qdrant_spike/` → the archive project's `data/qdrant_spike/`.
4. Bring Qdrant up inside the archive container from the moved dir (same env:
   `QDRANT__STORAGE__STORAGE_PATH=<archive>/data/qdrant_spike/storage`), map
   container port 6333 → a distinct host port (suggest **6343**).
5. Smoke test: `curl :6343/collections/splade_150m` shows the collection with
   the expected point count; run one known query via `qdrant_client` and
   compare against a committed parity record.

## 3. Phase 3 — SPLADE db accessibility (and the attached architecture decision)

**Constraint:** Qdrant storage is single-writer file-locked. Never bind-mount
the same `storage/` into two live Qdrant processes. Sharing = **HTTP API**, one
Qdrant process, wherever it lives.

- Archive container: local access at `localhost:6333` (it owns the process).
- Dev container (if/when needed): `SFU_SPLADE_QDRANT_URL=http://host.docker.internal:6343`
  (or the ClaudeBox container-network name, mirroring the Pommel
  `claudebox-<project>-pommel:port` pattern). The retriever already reads this
  env var — zero code change.

**The decision this forces:** Qdrant is TODAY'S DEFAULT SPLADE backend
(`SFU_SPLADE_BACKEND` default `qdrant`, flipped 2026-06-24). Moving it out
means the dev container's served SPLADE leg must flip to
`SFU_SPLADE_BACKEND=seismic` + `SFU_SEISMIC_SHARD_MANIFEST=<dv manifest>`
(+ `SFU_SEISMIC_LOAD_MODE=mmap`, federation per deploy). Known state going in:
corpus parity 0.9906 accepted 2026-07-05, shards 1–2 at 0.985 (E8/Q1 is the
pre-registered recovery lever). Options:
  - **(recommended)** flip dev to seismic now; the archive Qdrant stays
    reachable via the URL env as the instant rollback (one env var back).
  - or keep dev pointed at the archive Qdrant as default until E8 lands, and
    treat the flip as a separate later commit.

House rules on the flip commit: `docs/THIN_CLIENT_SWAP.md` (default change),
`docs/README.md` if docs move, same commit. Two known non-blocking bugs in the
seismic serve path should be fixed BEFORE the flip (from the 2026-07-06 bug
check): the filtered-query under-fetch in `_splade_leg_seismic`, and manifest
shard-count validation in `_load_manifest`.

## 4. Phase 4 — code hygiene in dev (optional, after the flip proves stable)

Keep the BMP/Qdrant code paths in dev initially (they're tiny and env-gated;
deleting them is not what frees the space). Only after a stable week: consider
stripping the BMP branch from `retriever.py`/`builder.py` on the main line —
the code stays alive on `archive/bmp-qdrant`. Every removal commit follows the
same-commit doc rule (THIN_CLIENT_SWAP.md + archive/bmp_decommission_plan/).

## 5. Phase 5 — clear the remaining non-Seismic paths (with two decisions)

Straightforward moves/deletes: `data/thinclient_1m`, `data/thin_client_poc`,
`spike/mmap_bmp` → archive; `tmpclaude-*`, `.handoff_extract`,
`sfu library mcp-handoff.zip` → delete; `data/dense_compression`,
`data/sectioned`, `data/thinclient_test_resume` → archive (or delete once the
eval-result JSONs they produced are confirmed in `data/eval_results/` + git).

- **DECISION A — `spool_backup/` (123 GB).** It is the regeneration source for
  BOTH the Qdrant ingest and the Seismic G7 shard builds (the stock
  `.index.seismic` sources live on volatile /tmp and are "regenerable from
  spool_backup"). Deleting it makes the dv shards effectively irreplaceable
  short of a full re-encode. Recommend: move to the archive container (it's a
  build source for both archived lines too) or cold storage; do NOT delete.
- **DECISION B — `openalex_snapshot/` (55 GB).** Corpus download/indexer
  checkpoints — only needed to resume/extend corpus ingest. If ingest is
  considered done, archive it; keep only if a 150M→250M extension is still
  planned (the watchdog's build-spool-par target was 250M).

## 6. Phase 6 — verification + doc sync (same push as the work)

1. Dev smoke: full test suite (`scripts/tests/`), then one live
   `search_academic` through the MCP server with the seismic leg serving; check
   the metrics JSONL shows all three legs healthy.
2. Archive smoke: Qdrant collection query parity vs a committed record; one BMP
   1M-section search via the `bmp` code path on `archive/bmp-qdrant`.
3. Rule Zero audit: `find data/seismic_150m -newermt <start>` → untouched.
4. Doc sync (house rules): `THIN_CLIENT_SWAP.md` (new default + Qdrant location
   + archive-container section), `STORAGE_BUDGET_150M.md` (new resident/disk
   numbers), `docs/README.md` index, dated SUPERSEDED banners where applicable.

## Rollback

Nothing in Phases 1–2 is destructive (moves, not deletes; deletes only in
Phase 5 after archive copies verified). Serving rollback at any point =
`SFU_SPLADE_BACKEND=qdrant` + `SFU_SPLADE_QDRANT_URL=<archive:6343>`.
