# Interacting with the SFU library thin client (optional)

**Status:** ACTIVE (interface notes as of 2026-10-29; the thin client is a
separate project — re-verify against its `docs/THIN_CLIENT_SWAP.md` before
relying on these)

This spike does not import the thin client. If you want its 150M-work
scholarly index (plus live OpenAlex fallback) as a second evidence leg, or its
measured results as metrics, use the interfaces below.

## 1. HTTP search endpoint (what `evidence/thinclient.py` calls)

Server module in the thin client: `source/sfu_library_mcp_http.py`. Default
local port in that project's deployment notes is 8788 (check its `/health`).

```
POST {base}/api/search
Content-Type: application/json
{"query": "<text>", "limit": 10,
 "year_from": 2020, "year_to": 2026,          # optional; a range may route to live OpenAlex
 "open_access_only": false, "type": "article"} # optional
→ {"results": [ <work dict> ... ], "meta": {"count": N}, "notes": [ "<human-readable note>" ]}
```

Work dicts carry (as read on 2026-10-29) `title`/`display_name`, `abstract`,
`doi`, `openalex_id`, `publication_year`, and a `score`. Results may be served
from a read-through cache; a degraded live leg is reported in `notes`.

```
GET {base}/health            → status, tool count, warm state, counters (NOT coverage)
GET {base}/api/index_status  → {"metrics": {"coverage_end": "YYYY-MM-DD", ...}}  # last date the LOCAL index covers
GET {base}/api/personas
POST {base}/api/search_stream (SSE; gated by SFU_SEARCH_DRAFT_STREAM, default off)
```

Enable in `config.toml`:

```toml
[thinclient]
enabled = true
base_url = "http://localhost:8788"
```

Quick check from the shell:

```bash
curl -s -X POST http://localhost:8788/api/search -H 'Content-Type: application/json' \
  -d '{"query": "zstd dictionary compression abstracts", "limit": 3}' | python3 -m json.tool | head -40
curl -s http://localhost:8788/api/index_status | python3 -c 'import sys,json; print(json.load(sys.stdin)["metrics"]["coverage_end"])'
```

## 2. MCP tools (if you give tier 2 the thin client as a tool server)

The thin client's MCP server (`source/sfu_library_mcp_server.py`, run with that
project's venv `/workspaces/sfu-library-thinclient/.venv/bin/python3`) exposes,
among others: `search_academic`, `search_by_author`, `search_by_doi`,
`search_by_topic`, `get_citations`, `get_references`, `get_paper_summary`,
`find_open_access`, `get_full_text_link`, `save_to_zotero`,
`batch_save_to_zotero`, `get_index_status`, `list_personas`, `reload_index`.
A tier-2 `mcp.tier2.json` would point at that server; see that project's
`docs/THIN_CLIENT_SWAP.md` §"Full MCP tool surface" for the current list and
launch command. Note `save_to_zotero` exists there: the thin client can push
works into the same Zotero library this auditor reads from.

## 3. Pommel code search (that project's semantic code index)

Not needed by the auditor. If a tier-2 reviewer should look inside the thin
client's code, the HTTP fallback is `POST http://localhost:7424/search` with
`{"query": "...", "limit": 5}` (port map in that project's
`docs/infrastructure/POMMEL_ACCESS.md`, untracked).

## 4. Metrics files

The numerical base of truth here is `fixtures/metrics/` — copies of six
`data/eval_results/*.json` files (see `MANIFEST.md`). To refresh, copy more
JSON files from that directory; never write back. The thin client's own rule
is that numbers in its docs must match these files, so they are a clean
example of a "measured" store. Each file names its producing script and the
doc that cites it.

## 5. What this spike must never do to the thin client

- Import from `source/` or `scripts/` (it does not).
- Write under `data/` (it does not; `data/seismic_150m/` there is irreplaceable).
- Edit its docs or indices. The spike lives in `spike/truth_drift_auditor/`
  only and is designed to be moved out.
