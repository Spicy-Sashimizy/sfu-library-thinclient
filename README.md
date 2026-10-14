# sfu-library-thinclient — "Duck Library"

Duck library is a hobbyist project by Gordon Chan to create an academic search engine for a 150-million-document corpus (OpenAlex). It scales from a laptop to server-grade compute. No search clusters and no JVM needed.

- BM25F lexicana leg powered by Tantivy. Fully controllable via subject/era section;
- SPLADE learned-sparse leg served by SEISMIC from eight immutable mmap shards (promoted 2026-07-06);
- an optional dense leg (default OFF since the 2026-08-18 ablation);
- app-side RRF fusion, a cross-encoder rerank, a read-through result cache, and a speculative draft/verify path;
- exposed as MCP tools (Claude Desktop) and as a web GUI (/app).

Documentation for the search engine decision, storage lever and latency number was measured here and is recorded in docs/. A work-in-progress thumb drive portable client ships from its own repo (scaffold/).

This personal project is clearly a vibe-coded personal project. It is not affiliated with or endorsed by Simon Fraser University; there may be leftover identifiers saying SFU. Visible branding is "Duck Library". This project was inspired by the closed-source academic search used at the SFU library, and the project's old name reflected that.

Please note that an LLM populates everything in tables and beyond the initial README.

## Start here

| Want to… | Read |
|---|---|
| understand the current architecture | `docs/THIN_CLIENT_SWAP.md` — the canonical "what runs here now" |
| find any document, decision record or measurement | `docs/README.md` — the index of all documentation, with Active / Deferred / Closed tables |
| run the server or the tests | `source/README.md`, `scripts/README.md` |
| see the evidence behind a number | `data/eval_results/INDEX.md` (file → date → citing docs) |
| rebuild a servable index yourself from public data, or re-score a headline number | `docs/REPRODUCIBILITY.md` — one command from the OpenAlex snapshot (measured: 50,000 works → served in 182 s), what is and is not reproducible without the 150M index |
| contribute, or understand the house rules the work was done under | `CONTRIBUTING.md`, `.claude/CLAUDE.md` |

## Repository map

| Directory | What | README |
|---|---|---|
| `source/` | serving code: HTTP + stdio MCP entry points, `lib/` (clients, rerank, cache), `lib/thinclient/` (retriever, SEISMIC backends, builders), `tests/` | `source/README.md`, `source/lib/README.md` |
| `scripts/` | operator entry points at the root (build, stage, serve, parity, GUI build/verify); families: `seismic_testbed/`, `experiments/`, `tests/`, `demo_broker/`, `gui_testbed/`, `portable_*`, `repo_tools/`, `archive/` | `scripts/README.md` |
| `docs/` | every subsystem, decision record and measurement campaign; `archive/` (closed research) and `deprecated/` (obsolete infra) are not current | `docs/README.md` |
| `web/` | the search-suite GUI: vendored React, precompiled JSX, no build server | `web/README.md` |
| `spike/` | vendored engine forks (SEISMIC, vectorium, toolkit) and spike code; `delta_ingest/` is active; `archive/` is closed | `spike/README.md` |
| `data/` | runtime artifacts (the served index lives on the host only: irreplaceable, read-only) and `eval_results/` evidence (in git) | `data/README.md` |
| `models/` | encoder / reranker models (local) and the model-versions registry (in git) | `models/README.md` |
| `scripts/archive/deploy_opensearch_era/` | OpenSearch-era deployment tooling — **legacy** | `scripts/archive/deploy_opensearch_era/README.md` |
| `scaffold/` | founding seed of the portable-client split repo | `scaffold/README.md` |

Development harness, not part of the software: `.claude/` (agent rules,
executed plans, hooks — `.claude/README.md`) and `.gitleaks.toml` are in
git; the owner's container, dashboards, code-search sidecar and host
launchers are local tooling outside the repository (see the dev-harness
block of `.gitignore`).

## Running it

**Without the 150M index** (any machine): build your own corpus from the
public OpenAlex snapshot and serve it — `docs/REPRODUCIBILITY.md` §2,
`scripts/reproduce/rebuild_from_openalex.py --work /var/tmp/duck_rebuild --download 1 --limit 50000`.
The measurements and the frozen relevance judgments behind every number are
in git; the served index, the model weights and the built Rust tools are not
(§1 of that doc says exactly which).

**With it** (this container):

Everything runs through the project venv (`.venv/bin/python3`) inside the
devcontainer; the served index and models are local artifacts that are not in
git (see `data/README.md`, `models/README.md`).

```bash
scripts/stage_seismic_local.sh        # once: copy the SEISMIC shards to local disk
scripts/serve_http.sh                 # HTTP server on :8080, GUI at http://localhost:8080/app
.venv/bin/python3 -m pytest -q        # test suite (source/tests + scripts/tests)
```

## Status and conventions

- Measured claims only. Anything unmeasured is marked *est.* or
  "IMPLEMENTED, EFFICACY UNMEASURED". Numbers in a newer doc supersede older
  ones; the superseded doc says so with a dated note.
- Closed tracks are banners + moves, never silent deletions
  (`docs/README.md` §Closed tracks). Dead code is kept under `*/archive/` as
  evidence.
- Code carries no inline comments (policy 2026-09-01); constraints live in
  `docs/CODE_INVARIANTS.md`, `docs/CODE_INVARIANTS_SCRIPTS.md`,
  `docs/ENV_GATES.md`, `docs/EXTERNAL_API_CONTRACT.md`.
- **License: not yet chosen.** The per-component licensing facts are in
  `docs/infrastructure/PORTABLE_LICENSING_INVENTORY.md`; the owner's sign-off
  is pending, so no LICENSE file is in the repo yet. Cite with `CITATION.cff`.
