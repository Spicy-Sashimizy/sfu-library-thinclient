> **CLOSED SUPERSEDED 2026-10-11** — OpenSearch-era droplet+TrueNAS deploy tooling; current deployment is scripts/demo_broker/ (OCI demo) and scripts/serve_http.sh locally

# scripts/archive/deploy_opensearch_era/ — legacy deployment tooling (record)

**Status:** CLOSED SUPERSEDED 2026-10-11

These files deployed the OpenSearch-era MCP server to a TrueNAS box
(and a DigitalOcean droplet). They lived in `deploy/` until 2026-10-11, when
the codebase triage moved them here (`git mv`, basenames kept; root
`requirements.prod.txt` came with `Dockerfile.prod`, its only consumer).
The current public deployment is the OCI demo (`scripts/demo_broker/`,
`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md`); the current local serve path
is `scripts/serve_http.sh` (`docs/THIN_CLIENT_SWAP.md`). The design records
live in `docs/deprecated/` (`CLOUD_OFFLOAD_AND_MONITOR_PLAN.md`,
`truenas_setup.md`).

Not runnable as-is: relative paths inside the files (`context: ..`,
`dockerfile: deploy/Dockerfile.prod`, `deploy/*.sh` usage lines) assume the
old `deploy/` location, `Dockerfile.prod` installs only
`requirements.prod.txt` (no tantivy/numpy/torch, so it cannot serve the
thin-client path), and `mcp_http.supervisor.conf` points at
`/workspaces/sfu-library-mcp-training/`, which does not exist in this
container. Kept as the record the deprecated docs cite.

| File | What it was |
|---|---|
| `Dockerfile.prod`, `docker-compose.prod.yml`, `.dockerignore` | production image + compose for the OpenSearch-era server on TrueNAS |
| `requirements.prod.txt` | the image's pip set (moved from the repo root 2026-10-11) |
| `deploy.sh`, `deploy-rsync.sh`, `update.sh`, `logs.sh` | push / update / tail the TrueNAS container |
| `healthcheck.sh`, `health_check.py` | health checks for that container (shell and Python twins) |
| `mcp_http.supervisor.conf` | supervisord program keeping the HTTP server warm (cited by `docs/infrastructure/REMOTE_MCP_ACCESS.md` Path A) |

Deleted 2026-10-11: `deploy/__init__.py`,
`deploy/reindex_autoresume.supervisor.conf`, `deploy/demo_droplet/`. Moved
2026-10-11: `deploy/ntfy/` → `scripts/demo_broker/ntfy/` (the live NAS
notification relay). Constraints recorded from these scripts:
`docs/CODE_INVARIANTS_SCRIPTS.md` §scripts/archive/deploy_opensearch_era/.
