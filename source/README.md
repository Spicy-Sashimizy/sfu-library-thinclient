# source/ — the serving code

**Status:** ACTIVE

Everything that runs when the search stack serves a query. The architecture
(engines, index layout, environment gates, MCP tools, web API) is documented once, in
`docs/THIN_CLIENT_SWAP.md`; constraints that used to live in code comments are
in `docs/CODE_INVARIANTS.md`; every `SFU_*` environment gate is in
`docs/ENV_GATES.md`. Code here carries no inline comments by policy
(2026-09-01) — docstrings only.

| Path | What |
|---|---|
| `sfu_library_mcp_http.py` | HTTP entry point (Starlette/uvicorn): `/api/*` for the web GUI, `/app` static files, `/health`, `/analytics` + `/engagement` (GUI tracking endpoints, wired 2026-10-12), the result cache and speculation plumbing. Start it with `scripts/serve_http.sh` |
| `sfu_library_mcp_server.py` | stdio MCP entry point for Claude Desktop (same tool set, `lib/tools.py`: 18 tools registered as of 2026-10-13, cut from 27 on 2026-10-12) |
| `lib/` | the package — serving stack, external clients, and a few legacy modules; map in `lib/README.md` |
| `lib/thinclient/` | the index-side package: builders, sidecars, the retriever and the SEISMIC backends; map in `lib/thinclient/CLAUDE.md` and `lib/README.md` |
| `tests/` | the `source` half of the pytest suite: 27 `test_*.py` files as of 2026-10-13 (the other half is `scripts/tests/`; both run from `pytest.ini` at the root). `manual_smoke_mcp_tools.py` is the only non-pytest file left (a print-style smoke script) |

Run (from the repository root, always the project venv):

```bash
scripts/serve_http.sh                                   # HTTP server on :8080, GUI at /app
cd src && ../.venv/bin/python3 sfu_library_mcp_server.py   # stdio MCP server
.venv/bin/python3 -m pytest -q                          # whole suite (source/tests + scripts/tests)
```
