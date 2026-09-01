# sfu-library-thinclient

Local-first academic search over a 150M-doc corpus: tantivy BM25F +
SEISMIC-served SPLADE (8 immutable mmap shards) + dense leg, fused with RRF —
no OpenSearch, no JVM. This container is the **research testbed, artifact
factory, and parity oracle** for the stack (the portable client ships from
its own repo — see `scaffold/portable_client_seed/`).

**Start here:** `docs/THIN_CLIENT_SWAP.md` (current architecture) ·
`docs/README.md` (index of ALL documentation — every subsystem, decision
record, and measurement campaign).

| Dir | What |
|---|---|
| `src/` | serving code (MCP server, retriever, thinclient package) |
| `web/` | the search suite GUI (`/app`; visible branding "Duck Library", identifiers keep sfu naming; JSX in `web/src/` compiled by `scripts/build_web.mjs`) |
| `scripts/` | family-organized tooling — see `scripts/CLAUDE.md` for the map |
| `docs/` | indexed documentation; measurements + decision records |
| `data/` | runtime artifacts (indexes, eval evidence) — mostly not in git |
| `spike/` | vendored engine forks (live) + `archive/` (killed tracks) |
| `models/` | encoder models (SPLADE ONNX fused, dense) |
| `scaffold/` | founding seed for the portable-client split repo |

House rules for contributors (human or agent): `.claude/CLAUDE.md` — the
git workflow, doc-freshness discipline, venv rules, and the 2026-09-01
no-internal-code-comments policy (constraints live in
`docs/CODE_INVARIANTS*.md` / `docs/ENV_GATES.md`) are mandatory.
Measured-claims-only in docs; unmeasured is marked *est.*
