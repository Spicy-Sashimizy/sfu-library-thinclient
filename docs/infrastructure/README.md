# infrastructure/ — running, reaching, deploying and maintaining the system

**Status:** ACTIVE

Entry point for everything that is not retrieval research: repository
ledgers and policies, access runbooks, the public demo, portable builds and
the GUI specs. One row per doc; each doc's own banner carries its status and
dates. Retrieval research lives in the other `docs/<track>/` directories.

## Repository ledgers and policies — the CLAUDE.md section

`SCRIPT_HYGIENE_POLICY.md` is binding (referenced from `.claude/CLAUDE.md`);
the ledgers are the dated record of every repository-wide change.

| Doc | What it is |
|---|---|
| `SCRIPT_HYGIENE_POLICY.md` | **Binding policy (2026-10-11)**: script placement, `Lifecycle:` header for new scripts, the substantial-change gate (restore tag + fast tests + function inventory before any commit of ≥10 files / ≥500 lines / any code delete or rename), the three hook layers, the triage method. Code in `scripts/repo_tools/` |
| `REPO_AUDIT_2026-07-17.md` | the earlier three-agent organization/hygiene/git audit whose deferred reorganization plan the 2026-10-10 session executed in part |
| `REPO_REORG_2026-10-10.md` | the 2026-10-10 reorganization + dead-code audit ledger: every move (old → new → commit → references repointed), per-module audit table, test baseline |
| `REBRAND_DUCK_LIBRARY_2026-10-10.md` | the "SFU Library" → "Duck Library" rebrand ledger: per-commit revert table, compatibility aliases, every identifier that still says `sfu` and why |
| `PUBLIC_PREP.md` | publication note: the repository has been public since 2026-10-13 |
| `SCRIPT_TRIAGE_2026-10-11.md` | script triage ledger: 402/402 files under `scripts/` classified line by line (audited by `scripts/repo_tools/triage_audit.py`); 12 moves, 3 deletions, 36 banners |
| `CODEBASE_TRIAGE_2026-10-11.md` | codebase triage ledger: every tracked file under `source/ web/ spike/ deploy/ .claude/ models/ scaffold/` and the root, at file and symbol level; per-group commits, the dead-code guard's first green state |
| `OWNER_DECISIONS_2026-10-12.md` | owner decisions wave: Qdrant leg removed, MCP tools 27 → 18, analytics + engagement GUI wired, requirements regenerated, dense KEEP, speculation + cross-encoder flip DEFERRED; items still pending |
| `PORTABLE_LICENSING_INVENTORY.md` | **INVENTORY ONLY, no legal clearance (2026-09-29)**: one row per redistributable handout component (shipped models and base-checkpoint provenance, OpenAlex CC0 and the reconstructed-abstract question, runtime wheels, the seismic/vectorium/toolkit forks and statically linked crates, python-build-standalone, the project's own code — no LICENSE file yet); feeds `PORTABLE_STACK_MANIFEST.md` §(d) row 3, which stays open pending owner sign-off |

## Access and environment

| Doc | What it is |
|---|---|
| `REMOTE_MCP_ACCESS.md` | connecting Claude to the Duck Library MCP server from outside the container (Cloudflare tunnel, `scripts/setup_cloudflare_mcp.sh`) |
| `INDEX_WRITE_PROTECTION.md` | **2026-09-30**: what protects the irreplaceable `data/seismic_150m/` — verified state, incidents to date (none touched an original), code guards and baseline checks, partial chmod, and the operator steps for OS-level enforcement (read-only bind mount, host ACL, backup + SHA-256 manifest) |
| `HEADLESS_GLM_DRIVE_RUNBOOK.md` | launch and monitor an autonomous GLM 5.2/CCR drive session (R2/R3-proven recipe, 2026-07-16) |

## Public demo (Oracle Cloud) — reopened 2026-10-06

The owner moved the tenancy to Pay As You Go on 2026-10-06; the E5 serve
instance was rebuilt from its preserved disks. Live policy: wake only on an
invite click, stop 60 minutes after the wake, 55 hours/month runtime cap
(CAD 40). Measured rebuild/wake/stop numbers: `scripts/demo_broker/README.md`
§"2026-10-06 revival". Between 2026-09-25 (cloud access ended, every cloud
host gone) and 2026-10-06 the demo was off the air and these two docs were
closed; their 2026-09-25 closure text is kept inside them as the record.

| Doc | What it is |
|---|---|
| `OCI_DEMO_DEPLOYMENT.md` | the canonical public-demo deployment: free-tier always-on broker + scale-to-zero full-150M compute on Oracle Cloud; payload measured 126.33 GB (`docs/STORAGE_BUDGET_150M.md`); cost model with the billed-line-verified cold-visit cost (USD 0.129 = CAD 0.185, 2026-09-01). Code `scripts/demo_broker/` |
| `DEMO_PAYG_PLAN.md` | the post-trial plan, option A executed 2026-10-06: Pay As You Go + scale-to-zero (measured idle floor CAD 0.359/day, hot CAD 0.482/hr), TrueNAS cold store, Always-Free A1/ARM parked |
| `../deprecated/oci_demo/` | the three demo docs that stay closed (`OCI_FREE_TIER_RESIDENT_DEMO.md`, `HYBRID_DEMO_DEPLOYMENT.md`, `DEMO_DEPENDABILITY.md` — the last one's in-container harness and measured numbers still stand as a local record). CLOSED DEAD 2026-09-25, `docs/README.md` §8 |

## Portable and handout builds

| Doc | What it is |
|---|---|
| `PORTABLE_STACK_MANIFEST.md` | authoritative manifest of the Qdrant-free, docker-free portable bundle (2026-07-17, WI-8): runtime imports with versions, per-leg artifact sizes, staging probe, installer delta list; §(e) the portable update path (`portable_bundle_updater.py`, crash-safe apply order). Open rows of §(d) are tracked in `docs/README.md` §6 |
| `PORTABLE_DATA_SHIPPING_RESEARCH.md` | how the portable build's per-shard data ships (2026-07-17, research only): subset-prebuilt + live-tail RECOMMENDED; rebuild-from-OpenAlex REJECTED for the handout (the outsider's rebuild path is `docs/REPRODUCIBILITY.md`) |
| `PORTABLE_LINUX_BUNDLE.md` | **MEASURED 2026-09-27**: deterministic, relocatable Linux x86-64 runtime bundle (`scripts/portable_linux/`): python-build-standalone CPython 3.11.16 + hash-locked CPU-only wheels + the v3 seismic `.so`; 1.18 GiB, builds byte-identical, relocation and import check PASS, one-query smoke PASS; no index data or weights |
| `PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` | **DESIGN (2026-08-04)**: run-from-thumb-drive native-Windows build cut to `social_sciences` (dense stripped, offline abstracts, seismic subset ~34 GiB); size budget, cold-section wargame, Windows-port plan. Code `scripts/portable_socsci/` |
| `PORTABLE_LICENSING_INVENTORY.md` | see the ledgers table above |

## GUI

| Doc | What it is |
|---|---|
| `GUI_BAREBONES_PROGRESS_SPEC.md` | the bare-bones-default + honest-search-progress GUI contract (2026-07-17; implemented in wave 5, WI-15). The shipped GUI is `web/` (`web/README.md`, `docs/THIN_CLIENT_SWAP.md` §Web GUI) |
| `GUI_INTERACTION_TESTBED_PLAN.md` | the full-interaction testbed (2026-07-17, **BUILT + MEASURED**, WI-16): enum sweep, model walk, seeded-gremlins chaos, continuous resize, one invariant oracle; code `scripts/gui_testbed/` |
| `WEBGUI_RELIABILITY_RESEARCH.md` | seven-layer GUI redundancy map onto the existing `/app` suite (2026-07-17, research only) |
| `GUI_REFERENCE.md` | **historical, nothing of it built** (banner 2026-09-01): the early UI research that recommended forking FAIRplexica (Next.js + LLM query parsing); kept as reference only |
