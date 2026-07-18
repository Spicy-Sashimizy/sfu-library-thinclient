# Bootstrap plan — first sessions in the new container

Ordered; each step gate-checked before the next. GLM-wave-able (the
deployprep runbook pattern; ~34 min/item baseline from the 2026-07-17
campaign) or hand-driven.

## Phase 0 — container birth (one session)
1. Copy this seed: `bash /workspaces/sfu-library-thinclient/scaffold/portable_client_seed/import_fixtures.sh <this-repo-root>`
   (imports goldens + manifest + spec snapshots; then `mv` seed docs into
   place: CLAUDE.md → repo root, CONTRACT.md, BOOTSTRAP_PLAN.md → `docs/`).
2. `cargo init --name sfu-portable` workspace: crates `parity` (the differ),
   `orchestrate` (RRF/dispatch/hydration, empty), `bundle` (updater, empty).
3. `.gitignore`: `/artifacts/`, `/bundles/`, `target/`, imported binaries.
4. First commit = seed + empty workspace + green `cargo test` (no-op).

## Phase 1 — parity harness BEFORE features
5. `parity` crate: load `fixtures/topk_goldens_*/`, run the seismic crate
   (git dep on the oracle's fork) over an imported shard, diff (id, score)
   bit-exact. Bar: green vs native goldens on x86-64-v3 build.
6. CI (GitHub Actions): fmt + clippy + parity-on-fixture-stub per PR.

## Phase 2 — the cross-build probe (the iPhone-hypothesis gate)
7. aarch64 build (Apple Silicon runner or cross): parity + warm-ratio
   gates recleared per WI-4 methodology, worst-case-shard rule, n≥100.
   THIS is the est.→measured converter for the whole ARM story.

## Phase 3 — orchestration port
8. `orchestrate`: sequential federation first (the portable serving mode —
   measured 0.27 GB resident / parity 0/2000 in the oracle, WI-1), then
   RRF + hydration. Parity-gate every PR against the Python path's goldens
   (extend goldens to full-RRF fixtures via an oracle-side request).

## Phase 4 — shell + bundle
9. Tauri shell implementing `GUI_BAREBONES_PROGRESS_SPEC` (Tier 0 only at
   first); reuse the reliability layers L1/L4/L5 natively.
10. `bundle` crate: WI-14 delta contract (check/apply/rollback), resumable
    chunked fetch. Fixture-bundle proof like the oracle's 2026-07-17 run.

## Open decisions to force early (do not let them drift)
- Windows: native port vs Linux/WSL2-only (halves or doubles scope).
- Model licenses (SPLADE/dense) — blocker for ANY public handout.
- Subset corpus: blocked on oracle-side host-tier spool re-export +
  `cited_by_count` (oracle doc 16) — the client can be built and gated
  entirely on 150M shard fixtures meanwhile.
