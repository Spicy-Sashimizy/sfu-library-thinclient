# Code invariants — scripts/ (and the deploy/ tooling archived 2026-10-11) (migrated from code comments 2026-09-01)

**Status:** ACTIVE

Companion to `CODE_INVARIANTS.md` (source/). Same rules: constraints migrated
from code comments live here, ordered by area, terse, with file pointers.
Research/evidence harnesses (`scripts/seismic_testbed/`,
`scripts/experiments/`, `scripts/archive/`, `spike/`) were NOT stripped —
pre-registered bars live in harness source at evidence commits by project
methodology — but their most reusable knowledge is mirrored in the last
section so it is grep-reachable from docs.

## scripts/repo_tools/ — hygiene checker, symbol inventory, preflight gate (added 2026-10-11; doc `infrastructure/SCRIPT_HYGIENE_POLICY.md`)

- **check_script_placement.py**: `SCRIPTS_ROOT_ALLOW` and `SCRIPTS_FAMILIES`
  MUST mirror the tables in `scripts/README.md`; a new family or root entry
  point changes both in one commit or the pre-commit hook rejects the add.
  The lifecycle header is read from the first 20 lines only. Grandfathering
  reads the tree of `SFU_PLACEMENT_BASELINE_REF` (default tag
  `pre-rust-core-and-script-triage-2026-10-11`); if the tag is missing it
  falls back to HEAD, which grandfathers everything — never delete that tag.
  With `--content -` the content is applied only when exactly one path is
  given. Runs under `python -I` from hooks: no repository imports.
- **symbol_inventory.py**: keys are `basename::qualname`, so a `git mv` that
  changes the basename reports every symbol as removed + added — keep
  basenames on moves or record the rename in the ledger. Nested functions
  are not inventoried (only module- and class-level defs). Files that fail
  to parse contribute no symbols (a syntax error in a moved file would hide
  its symbols; the tests catch the import error instead).
- **preflight.py**: the stamp's `tree` is `git write-tree` over the INDEX, so
  it must run after the final `git add` and before `git commit`; any later
  staging invalidates it by design. Tag freshness is 24 h or == HEAD; the
  tag push failing is a warning, not a failure. Default test set excludes
  `scripts/tests/` (80 s collection, 3 GB RSS guard on `test_delta_*` in one
  process); override with `SFU_PREFLIGHT_TESTS`. Thresholds:
  `SFU_PREFLIGHT_MIN_FILES` (10), `SFU_PREFLIGHT_MIN_LINES` (500).
- **triage_audit.py** (Fable audit of the 2026-10-11 ledgers): parses every
  table under the ledger directory (`--ledger-dir`) by header
  names (`Path`, `Class`, `Proposed action`); a ledger that renames those
  columns is silently skipped, so keep the template. Coverage is measured
  against `git ls-files scripts` (401 paths on 2026-10-11, README/CLAUDE.md
  included); DEAD rows re-run the reference search over tracked files only
  (never `data/`); results JSON `data/eval_results/script_triage_audit_<date>.json`.
- **hooks/pre-commit** is the tracked source; `.git/hooks/pre-commit` is a
  copy made by `install_git_hooks.sh` (previous copy backed up as `.bak.<ts>`).
  `post-commit` (public-branch generator, host-specific) is never touched.
  `.claude/.preflight_stamp.json` is gitignored.

## scripts/demo_broker/ (the OCI demo broker — REOPENED 2026-10-06)

> **2026-10-10:** the broker is live again since 2026-10-06 (`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md`, `DEMO_PAYG_PLAN.md`); the invariants below are its current contract. The 2026-09-25 note is kept as history. Known doc gap (audit 2026-10-10): `scripts/demo_broker/README.md` still says `DEMO_BEARER_TOKEN` is required on `/mcp`, but `/mcp` now checks per-session tokens and `Config.bearer_token` is read from the environment and unused.

> **STATUS 2026-09-25: CLOUD ACCESS ENDED.** The OCI E5 host and all DO
> droplets are gone; the broker, `watchdog.py` and the `DEMO_PIN_RUNNING`
> gate no longer operate anything. The invariants below are kept as the
> code's contract should a host return; none of them is live.

- **`DEMO_BROKER_LIVE=0` is the single gate between dry-run and real cloud
  spend.** `DEMO_CLOUD` default stays `do` so the DO deploy is untouched
  unless explicitly flipped to `oci`.
- OCI auth is deliberately explicit environment — never an implicit `~/.oci` read.
  Key passphrase and ntfy token environment variables accept a literal value OR a path to a
  secret file. `OCI_STOP_ACTION`: SOFTSTOP = ACPI shutdown then power off
  (default); STOP = hard power off (fallback).
- `OCI_INSTANCE_IP` (stable private IP) is the default proxy path — zero
  control-plane API calls per request; the VNIC-attachment lookup is only
  the fallback. The instance is never created or destroyed by the broker —
  START/STOP on a static OCID only.
- **Draft-cavage signing**: headers are signed in the exact order advertised
  in the Authorization `headers="…"` list — reordering silently breaks
  auth. Date header is RFC 1123 GMT (`email.utils.formatdate(usegmt=True)`).
  PKCS1v15 signatures are deterministic (tests rely on equality).
  `STOPPING` maps to DOWN (billing is ending; not serving).
- **Reconcile stored UP versus cloud state each poll** (incident 2026-08-20: an
  out-of-band stop left the broker believing UP forever — never re-woke the
  box, kept accruing phantom runtime). Health is checked first so a live
  serve is never reset by a transient control-plane error; only
  both-signals-down counts.
- **Cloudflare**: behind the CF proxy `request.client.host` is an edge
  node — the visitor's real address is `CF-Connecting-IP` (all per-IP
  limiting keys off it). Session-gated `/app`/`/api` responses are
  `private, no-store` — CF must never edge-cache them (observed live
  2026-08-21: cached search.js served past the cookie gate,
  cf-cache-status HIT). CF Browser Integrity Check 403s urllib's default
  UA (error 1010) — the ntfy sink sits behind CF, so notify sends a
  browser-ish UA; notification failure never propagates into the request
  path.
- **MCP proxying**: the response body is streamed by a generator, NOT a
  context manager — a buffered `.read()` would hang on long-lived SSE
  (text/event-stream). `Mcp-Session-Id` is forwarded and clients must echo
  it. Only `tools/call` is billable — the MCP handshake
  (initialize/tools/list/notifications) never exhausts quota.
- **Admission control**: per-session caps can't stop N visitors stacking
  simultaneous searches (serve engine semaphore = 8; measured 2026-08-20:
  15 concurrent held but per-request p50 grew to 5.5–8.3 s). Global switch:
  6 billable slots cross-session, `DEMO_MCP_RESERVED_SLOTS=2` are
  MCP-priority — GUI may hold only (max − reserved) while ANY MCP call is
  in flight but borrows the full budget when MCP is idle; no preemption.
  `/api/arch-search` is unauthenticated but rate-limited per IP (5/min) and
  counts against the serve box's own semaphore, not the broker slot
  tracker. `/api/unpack` is owner-only (same posture as blocked Zotero
  write tools on `/mcp`). Share-detection state is deliberately in-memory
  (resets on restart; catches active sharing only).
- **Scheduler decision order = the spend policy**: hard killswitch (budget
  backstop) overrides everything → business hours keep-hot (boot if down,
  never reap on idle) → after hours scale-to-zero (only an on-demand
  session keeps it alive). Runtime accounting clamps the live portion to
  today's local midnight so a run crossing midnight doesn't charge
  yesterday's hours against today's killswitch cap. Single-flight wake
  lock: 15 simultaneous clicks ⇒ one boot. Cost report's $0.50/hr is the
  g-16vcpu-64gb DO estimate. `DEMO_PIN_RUNNING=1` is applied at the single
  actuation point (`_destroy`), not in `decide()`: the decision is still
  computed and logged as `reap_suppressed`, but no stop action is ever
  issued. Required whenever a stop is irreversible (a post-trial tenancy
  has the paid shape's service limit at 0, so START would be refused).
- **`watchdog.py` is read-only**: it may call `instance_state()` and HTTP
  `/health` and write its own JSON state file; it must never call
  `start_instance`/`stop_instance`/`wake`/`sleep`. Alerts are edge-triggered
  (`evaluate` is pure): a recovery alert is sent only after a sent down alert,
  health alerts are suppressed while the instance is not RUNNING (the state
  alert already covers it), and the heartbeat fires at most once per local day.
- **RAM dial** (`dial.py`): rungs are deliberately allowed near the
  measured 10–11 GB thrash cliff (walking the cliff is the demo's point);
  4 GB floor keeps out of guaranteed-OOM, 64 GB = biggest boost shape.
  `MemoryMax = high + guard` (dial_guard_mb). Apply order is
  widen-then-narrow so max never transiently dips below high (wrong order
  can OOM the serve). systemd prints "infinity" as 2^63−1 via `show`;
  `MemoryCurrent` "[not set]" comes back huge — normalize to None.
  `DEMO_DIAL_BACKEND`: off ⇒ `/admin/dial` 404s; systemd ⇒
  `systemctl set-property --runtime`; cgroup ⇒ direct cgroup-v2 writes.
- **sfu-serve.service**: MemoryHigh (reclaim, never OOM) is the rung;
  MemoryMax is a backstop ~1.5 GB above. **`MemorySwapMax=0` is NOT
  optional** — every R1/R2 ladder cell was measured swap-forbidden; a
  swap-enabled dial measures something else. `serve_http.sh` `exec`s
  uvicorn so the serve inherits the unit's cgroup; ~93% of the working set
  is file-backed page cache. **sfu-broker.service**: dependency tree kept
  tiny (fastapi + uvicorn + cryptography, no `oci` SDK) for the 1 GB
  Always-Free box; the broker holds the OCI signing key.

## scripts/archive/demo_dependability/ (WI harnesses; bars also in docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md)

> **2026-10-11:** `build_demo_payload_manifest.py` and `seed_oci_volume.sh` moved to `scripts/demo_broker/` — they are the live upload procedure of the reopened OCI track (`infrastructure/OCI_DEMO_DEPLOYMENT.md`) and `scripts/tests/test_demo_payload_manifest.py` imports the first. Their invariants below still apply.

- **update_demo.sh (WI-13)**: STAGING ONLY (127.0.0.1, port 8197 — never
  the 8159/8180 demo ports), no served-default flip.
  `data/seismic_150m/` is READ-ONLY, always — the broken-shard fixture is
  a tiny COPY under `data/eval_results/_fixtures/`, never a real shard.
  The verify gate has two parts because `/health` reports
  `splade.configured="seismic"` whether or not shards loaded — the
  retriever silently falls back to BM25F on a broken shard set, so a 200
  `/search` alone would commit a silently-degraded update; `/verify`
  (`SFU_DEMO_UPDATE_VERIFY_SEISMIC=1`; gate retired 2026-09-25 with the archived harness, see `ENV_GATES.md` → Retired gates) forces the lazy seismic load (a
  plain `r._seismic` read returns None without loading; calling
  `_seismic_backend()` is what `search_rrf` does to trigger the mmap).
  Page cache is cooled between arms with fadvise-DONTNEED — a READ-ONLY
  hint on the shards, never a write (Rule Zero).
- **seed_oci_volume.sh**: re-entrant rsync (`--partial --append-verify
  --inplace`; single files up to 25 GB). **Transfer a QUIESCENT payload**:
  rsync'ing SQLite while a writer holds the WAL can capture a torn page,
  and `-wal`/`-shm` are excluded by construction so a torn copy is NOT
  recoverable. Manifest-driven — the script never walks the tree itself.
  `MAX_RETRIES 0` = retry forever; `BACKOFF` seconds capped at 300;
  `BWLIMIT` KB/s, 0 = unlimited. In `--verify` output a real diff is a
  FILE line whose first flag char isn't `.` (directory/timestamp lines are
  benign `--inplace` noise). `rc=$?` is captured explicitly (a bare
  `if rsync; then` reads the if-statement's status — the retry log would
  always claim rc=0).
- **reliability_soak.sh (WI-12)**: the pre-launch gate. Pre-registered
  bars: availability ≥95%; every fault produces a degradation + recovery
  event; worst-phase p95 ≤ ~5× warm baseline. **A 429 is a CLEAN shed,
  counted ok** — changing that changes the availability math. The soak's
  leg fault is a proxy (can't monkeypatch a running serve); a true leg
  fault is `wi9_fault_injection.py`.
- **WI-9**: guardian leg timeout is 30 s for a HUNG leg, not a slow one —
  warm diverse p50 measured up to ~10 s on 9p, so a tight 3 s would trip
  on a HEALTHY leg. `remote_abstracts=False` in the harness: batch
  OpenAlex fetches 429-storm and raise inside `_hydrate`, contaminating
  the fault proof with a network fault. onnxruntime/transformers' FIRST
  import must happen on the main thread (worker-thread first-import raises
  ImportError, mis-seen as a SPLADE failure); the first SPLADE query
  lazy-loads 8 shards (~8 s+ cold), which must not race the leg timeout.
- **leg_breaker.py**: each leg call runs in its OWN daemon thread — a
  SHARED executor was the WI-9 first-attempt bug (a hung SPLADE leg's
  abandoned worker starved the pool; BM25F/dense queued behind it and all
  three degraded). `except BaseException`: pyo3 PanicException is a
  BaseException — a plain `except Exception` misses Rust panics (also
  mirrored in `eval_parity_section_waves.py`).
- **staging_serve.py**: four-state warm contract
  (None/pending/warm/failed); the watchdog MUST wait for `warm` before
  declaring recovery. WI-11 shed: env-gated OFF; sheds with clean 429 +
  Retry-After, never an unbounded pileup; default capacity = 2× the WI-7
  warm knee (0% errors at c=32). Empty index_root silently targets the
  REAL serving root (`data/thinclient_index`) — `SFU_THINCLIENT_INDEX_ROOT`
  overrides. `/health` is deliberately lightweight (a cold 3-leg probe is
  ~minutes when shards first fault).
- **watchdog.py / wi3 / load_driver**: cold-start grace ≈ the systemd
  `StartLimitIntervalSec` a real deploy provides (~2 min cold load is not
  wedged). Serve subprocess gets `start_new_session=True` so SIGTERM
  reaches only it; the load driver kills the SERVE pid, not the watchdog;
  SIGTERM handler exists so the report still gets written. Back-pressure
  load model: a new request is submitted only as one completes.
- **build_demo_payload_manifest.py**: rank 0 of `SERVED_MANIFEST_LADDER` =
  the retriever's unset-env promotion default; the shards IT names ship,
  the rollback ladder stays on the build host. WAL/SHM never ship (live
  writer state; payload DBs are quiesced). Dropping the v3 `abstracts.sqlite`
  (−13.5 GB) only after the gate is verified on the BUILD host — the demo
  box cannot rebuild the locator. The int8 CE ONNX ships only as the
  single-stream fallback (measured slower at serve shape).
- **deploy_versions.py / portable_bundle_updater.py**: crash-safe apply
  order — fetch artifacts beside old (never in-place) → verify sha256 →
  **flip the bundle manifest LAST** (atomic pointer swap) → keep old files
  until post-flip verify. The 114 GB tantivy index is pointer-mode only
  (directory version from filenames+sizes, not a data checksum — avoids
  contending with the live serve on 9p). Relpath is the identity across
  versions (absolute bundle paths differ). Version pins bumped on rebuild:
  `so_version` (WI-4 build rev), `shard_version`. `seismic.__file__` is
  the `__init__.py`; the extension `.so` is the version probe target;
  probes open O_RDONLY.
- **wi8_portable_manifest.py**: probe imports use
  `importlib.util.find_spec` — importing would pollute `sys.modules` and
  self-fulfill the check (the earlier probe had this bug). The pyo3
  module's init is `PyInit_seismic`, so the specification NAME must be `seismic`.
  Versions via `importlib.metadata` dist names, not `__version__`.
- **wi6_warmup_recover.sh**: closed the WI-3 gap (829 dead-window errors,
  0 client OK — seismic lazy-loads on first `/search`). `EXTRA_ENV` passed
  via `env`, not `eval` (the earlier eval form swallowed the command —
  watchdog never launched; fixed 2026-07-17).
- **check_ce_direction.py / eval_ce_v1_vs_base.py**: junk-promotion audit
  injects real docs from UNRELATED pools (the serving failure mode that
  matters); latency measured at the exact serve shape (one batch of
  `_CE_CANDIDATE_POOL`=20). `RRF_K=60`, `CE_POOL=20` duplicate the serving
  constants deliberately.
- **wi10**: recall-retention bar [0.80, 0.95] ≈ 7/8 per the pre-reg.

## scripts/ top-level (build, ingest, serve, eval drivers)

- **snapshot_downloader.py (OpenAlex ingest, GPU)**: RMM memory resource
  must be set BEFORE importing cuDF — cuDF's C++ layer captures the device
  resource at first allocation and later `rmm.reinitialize()` doesn't
  update it (symptom: `cudaErrorMemoryAllocation` on tiny allocs). No
  `maximum_pool_size` cap — a hard cap caused `std::bad_alloc` →
  `std::terminate`. cuDF's GPU gzip rejects multi-member gzip (common in
  OpenAlex parts) → CPU decompress first. `requests.Session` is NOT
  thread-safe — one lazily-created Session per worker thread. Durability:
  the writer's partial buffer is persisted atomically alongside every
  checkpoint and reloaded on resume; buffer is persisted BEFORE advancing
  the checkpoint, so a crash re-processes a part (harmless — indexer
  upserts by deterministic `_id`), never silently loses records. The
  fallback path must use the same processing fn/schema as prefetch
  (hardcoding it once dropped the GPU path and `legacy_schema` → mixed
  schemas). Sizing: cuDF needs ~5–10 GB VRAM/part; HTTP timeout 300 s
  (parts run 500 MB–1.1 GB).
- **build_thinclient_index.py**: processes, not threads — parse/classify/
  spool is GIL-bound (measured: 4 threads ≈ 1.6k docs/s, same as 1).
  Spool first, progress file second (kill between the two resumes into a
  cheap finish-only pass; reverse order rebuilds). Fresh process per
  section: worker RSS accumulates ~0.35 GB/h (measured 2026-06-13, tantivy
  segment churn). Era directories that never reached a checkpoint are uncommitted
  garbage; failures don't raise mid-run (supervisord retries from
  checkpoints); orphaned `meta_<section>.sqlite` handled idempotently;
  pack only after the cold section's live directory is finished.
- **build_flat_blocks.py**: measured build rates — flat stage 13.47 GB
  source → 114.9 s local disk, → 878 s on 9p (budget the 9p rate; output ≈
  0.857× source). An allowlist controls what the script may touch inside a
  staging directory — anything else and it refuses rather than delete operator
  data. `abstracts.sqlite` may be deleted ONLY when every id is
  ordinal-addressable and dicts are rehomed. Verification counts use a
  dict, not a list (duplicate ids would inflate `ids_checked`). Symlink
  views live deliberately OUTSIDE the section directory. Publish = one
  atomic rename.
- **prime_result_cache.py**: primes with the GUI's exact default request
  shape (`{query, limit: 50}`, no filters — `web/lib/api.js
  buildSearchArgs`) so real clicks hit the planted key; error-shaped
  responses are never cached; sequential (never a parallel burst on the
  cross-encoder).
- **run_parity_safe.sh / eval_thinclient_parity.py**: ⚠ the BMP SPLADE leg
  is not mmap'd — ~3.07× on-disk resident, ~211 GB for the full set; the
  single-process path OOMs 24 GB hosts and can take down the whole
  Docker/WSL2 VM — refused by default, explicit opt-in only. Each engine
  runs in its OWN process (no `close()` hook; only process exit frees the
  working set). The memory guard samples MemAvailable and aborts before
  the kernel killer (150M-era OOM kills left no traceback). The dense warm
  cache (≤500k-doc RAM delta) is shed for evals unless explicitly kept.
- **eval_parity_section_waves.py** (archived, `scripts/archive/bmp_era/`):
  reused the live retriever's BMP constants verbatim (drift would diverge
  recorded ranking from production) — those constants were removed from
  `retriever.py` 2026-10-11, so it no longer imports against HEAD;
  `SFU_SKIP_BMP=1` while building wave lists; each wave a fresh process so
  BMP RAM frees; wave contributions provably within own top-K.
- **stage_seismic_local.sh / serve_http.sh**: 9p/virtiofs/NFS random page
  fault ≈ 0.5 ms (measured 2026-07-18: ~1830 faults/s; native local FS
  160–240× faster ~300k/s); a query faulting ~15k pages ≈ 8 s and page
  cache does not hold. `serve_http.sh` documents the staging environment matrix
  (result cache staging-ON was an owner-granted exception for that wave
  only; speculation default OFF — the owner flips defaults, not scripts).
- **setup_cloudflare_mcp.sh**: reads everything from gitignored `.env`;
  safe to re-run (WAF create-or-append, tunnel ingress MERGED, DNS
  create-or-skip).
- **build_web.mjs**: JSX → plain JS so the browser never runs the 3 MB
  in-browser Babel; first run MIGRATES `type="text/babel"` sources out of
  the HTML (destructive one-time rewrite); `_sidebar.jsx` is prepended
  into every app so all three render one sidebar source.
- **verify_web_jsdom.mjs / verify_web_progress.mjs / e2e_sweep.mjs**:
  React controlled inputs ignore `inp.value=` (use the native setter so
  onChange fires); jsdom lacks `requestAnimationFrame` (React 18
  createRoot needs a shim) and glues adjacent button labels in
  textContent (assert exact label on `aside button`, never body-wide
  regex); localStorage is getter-only on Window (shadow on the instance).
  The shell mounts apps via srcdoc (`about:srcdoc` frames; multiple
  iframes stay alive, operate on the VISIBLE one). Health `warm` flag:
  present → honored, absent → true (forward-compat). PREF_DEFAULTS has NO
  banner/degraded/pill keys — reliability signals are deliberately
  un-toggleable. savedHistoryNav defaults ON since 2026-07-18.

## scripts/experiments/ (research evals; these three moved from the top level 2026-10-10)

- **arxiv_fetcher / evaluate_sfu_queries / benchmark_embeddings**: arXiv
  caps 100/request + polite delay; OpenAlex polite-pool mailto fallback;
  api_key is stripped from error strings so it never lands in logs.
- **eval_result_cache_ab.py / eval_speculation_ab.py (protocol rules)**:
  genuine cold misses use fresh-per-run nonces; published speedups must be
  recomputable from stored p50 fields with raw arrays kept (F6 rule);
  nonce RNG is seeded, never `secrets` (reproducible transcripts). The
  HOST-NOTE-W9-3 post-mortem: hit-rate arms once banked impossible 100%s
  because query pools were reused across cells in one serve lifetime —
  pools must be disjoint per cell. Enter fires at `enter_t` REGARDLESS of
  speculative-store state (the wait-for-store probe inflated hit-rate by
  construction and was deleted); a fast FAILURE (<50 ms 500/429/empty)
  must not score as a hit.
- **build_presentation_metrics.py**: newest dated result file wins;
  hand-entered (non-JSON) numbers are explicitly marked as
  measured-in-docs.

## scripts/gui_testbed/

- The invariant oracle's hard bars: zero pageerror, zero console.error,
  zero horizontal overflow (>4 px fail, 2 px sub-pixel tolerance), event
  loop responsive within 2 s, and the honesty floor — mock/demo data on
  screen ⇒ demo pill visible, never hidden. The pill (`#sfu-demo-pill`) IS
  the source-of-truth signal (the plan's `window.SFUApi?.lastSource`
  oracle was wrong — api.js tracks source per-call).
- Playwright resolves from the npx cache, NOT node_modules — never
  `npm install playwright` into the repo. One mulberry32 PRNG seed drives
  everything (gremlins gets the same value) so failures replay
  bit-for-bit; failing seeds are replay-confirmed then committed to
  `regression_seeds.json` (run first, forever).
- Chaos arms: live / backend-dead / hang 15 s / 429+Retry-After:3 /
  storage-corrupt (4 localStorage garbage cases incl. the real prefs key
  with a 1 MB value). Screenshots are committed evidence; trace zips stay
  out of git (never commit multi-MB zips). Transient overflow/console
  noise during a click storm is not a crash.
- run_all caps monkey (3 seeds/4 s) and must PRESERVE the authoritative
  full-run per-layer JSONs (back up, restore after; capped roll-ups write
  to a distinct path so they never impersonate the full N=10 matrix).
- model_walk: THE MODEL IS THE SPEC (transcribed verbatim from
  `web/lib/interface_prefs.js` PREF_DEFAULTS + `_sidebar.jsx`
  SUITE_NAV_ITEMS). Toggles are click-toggles — set prefs deterministically
  before walking.
- a11y: vendored axe-core 4.10.1 (sha256 pinned in `a11y_scan.mjs`);
  measurement only — fix nothing outside web/ defect rules.
  static_server exists because importing the real serve pulls the whole
  MCP stack + 24 GB index; mock fallback + demo banner is the honest
  default state. `GUITB_HOST=0.0.0.0` exposes beyond localhost — default
  stays loopback.
- resize_sweep: 320→1920 by +16; text-zoom 0.5–2; DPR 1/2/3 as separate
  contexts (deviceScaleFactor can't change mid-run); mid-skeleton resize
  must not shift layout.

## scripts/portable_socsci/ (+ windows/)

- **space_assistant.ps1** (user-data-destroying primitive): sha256 → copy
  → re-hash and REQUIRE match → only then delete → record in manifest;
  delete is ALWAYS last (worst case = a verified duplicate left on the
  USB); the move is recorded BEFORE deleting so the ledger never lags a
  deletion; ledger written to temp then moved (crash-safe); corrupt
  manifest is never clobbered; offloaded files mirror their source path
  under `_offloaded\C\Users\…`. AUTHORED on Linux 2026-08-05, UNPROVEN on
  Windows until run there (same for install_wizard.ps1).
- **install_wizard.ps1**: CPU preflight AVX2 / x86-64-v3 is the hard floor
  for `seismic.pyd`; `PF_AVX2_INSTRUCTIONS_AVAILABLE = 40` (Win10+; older
  Windows returns false for unknown ids → degrades to warn). Bundle ≈
  66 GiB measured 2026-08-04 + 2 GiB headroom.
- **START.bat**: `sfu_runtime.cfg` KEY=VALUE contract (`MODE=pc|hybrid|usb`,
  `SEQUENTIAL=0|1`, `INDEX_ROOT`, `MODEL_ROOT`, `SEISMIC_BUNDLE_ROOT`);
  re-points the seismic manifest at wherever seismic lives now (drive
  letters move); binds to loopback only (single-user desktop app); waits
  for `/health` warm (WI-6: "up" ≠ "warm"); `SFU_SEQUENTIAL_MODE=1`
  advertises on /health so the web UI defaults its one-at-a-time queue ON.
  SETUP.bat launches the ps1 with an execution-policy bypass scoped to
  that one process. Line endings: launchers ship CRLF.
- **build kit**: never `target-cpu=native` for the shipped `.pyd`
  (spike/CLAUDE.md rule); the fixed cargo pin lives in the gitignored
  Cargo.lock (must ride along); python-build-standalone `install_only`
  layout provides the relocatable CPython; multi-GB build outputs/testbed
  data/nested git never ship. Offline verify serves entirely from the
  bundle (dense stripped, `remote_abstracts=False`); a serving fault is a
  FAIL, not a degrade.

## scripts/portable_linux/ (added 2026-09-27; doc `infrastructure/PORTABLE_LINUX_BUNDLE.md`)

- **The bundled CPython minor version is pinned to 3.11** because the
  shipped seismic `.so` is `cpython-311` (PyInit ABI). A PBS bump within
  3.11 is fine; 3.12+ needs a rebuilt `.so`. Every pin (PBS tag/asset/sha256,
  `.so` path/sha256, indexes) lives in `pins.conf`; bump
  `BUNDLE_RECIPE_VERSION` and re-measure when one changes.
- **The build installs ONLY from `serving_requirements_linux.lock.txt`**
  with `--require-hashes --no-deps --only-binary=:all: --no-index` from the
  wheelhouse. `bundle_tool.py lock` is the only writer of the lock; the
  PyTorch CPU index serves some wheels without a published hash, so `lock`
  hashes those by downloading them. No sdists (hence no `pyzotero`: its
  `bibtexparser<2` is sdist-only).
- **Determinism depends on three things** (each broke a build-to-build
  fingerprint before it was fixed, 2026-09-27): (1) `PYTHONDONTWRITEBYTECODE=1`
  while the bundle's python runs pip, else timestamped `.pyc` land in the
  bundle; (2) `pip install --no-compile`; (3) `fix-scripts` rewrites every
  console script whose shebang names the build path into the `/bin/sh`
  trampoline AND refreshes that script's `RECORD` row (hash + size) — the
  RECORD otherwise keeps the build path's hash.
- **Import path = one relative `.pth`** (`sfu_bundle.pth`: `../../../../ext`,
  `../../../../app/src`), resolved by `site` against site-packages, so it is
  relocatable. Never pip-install a seismic wheel into the bundle (the venv's
  `~~ismic`-style directories are what in-place `.so` swapping leaves behind).
- **Out directory must be fresh and outside the repository** (the script refuses a
  non-empty directory or any path under the repository; bundle output never enters git,
  and `data/seismic_150m/` is never written).
- **`BUNDLE_MANIFEST.json` excludes itself and `BUILD_REPORT.json`** and
  carries no timestamps, so two builds compare by `bundle_sha256` alone;
  wall-clock lives in `BUILD_REPORT.json`.
- **`bundle_check.py smoke` loads the real index**: on the shared host run
  it under `flock /tmp/sfu_latency_measure.lock`. It FAILs on any
  "falling back"/"failed" WARNING, because a SPLADE-leg failure degrades to
  BM25F-only silently otherwise. Leak check ignores torch's jit stub in a
  fresh `mkdtemp()` and placeholder `__file__`s like `torch.ops` → `_ops.py`.
- **The SPLADE model directory handed to the bundle must contain the tokenizer.**
  `models/splade_onnx_fused` has only `model.onnx` + `config.json`; the repository
  serve path finds bert-base-uncased via code-relative
  `_TOKENIZER_FALLBACK_DIRS` (`source/lib/opensearch_retriever.py`), which do not
  exist next to the bundle's `app/src`. Without it the SPLADE leg falls back to
  BM25F-only (measured 2026-09-27, smoke attempt 1). `smoke
  --splade-tokenizer DIR` symlinks a composite dir in a temp location.

## scripts/reproduce/ (added 2026-10-10; doc `REPRODUCIBILITY.md`)

- **rebuild_from_openalex.py**: refuses a `--work` under the repository's `data/`
  tree (9p, and `data/seismic_150m` is read-only). Passes
  `--flush-docs 1e9 --buffer-max-docs 1e9` so one run = ONE generation;
  the generation builder holds its `DocRecord`s in memory, so a single run
  is bounded by host RAM (~1 M works per 32 GB, *est.*). `serve.env` points
  `SFU_THINCLIENT_INDEX_ROOT` at the generation directory, NOT at the empty base +
  `SFU_DELTA_ROOT`: the latter returned blank title/year on 2026-10-10
  (hydration gap, UNMEASURED cause). Subprocess output is captured per step
  into `<work>/rebuild.log` (not streamed). `records_after_abstract_filter`
  counts records the adapter yielded, that is, after `normalize_openalex_work`
  dropped works without a usable abstract; input lines = `--limit`.
- **verify_rebuild.py**: PASS requires both legs (`bm25f`, `splade`) in the
  union of provenance, `n_with_title == n_hits` per query, the SEISMIC
  backend loaded, and no "falling back"/"failed" WARNING — the same silent
  BM25F-only fallback trap as `portable_linux/bundle_check.py smoke`.

## Test suite layout (`pytest.ini`, added 2026-09-25)

- `source/tests/` and `scripts/tests/` are both Python packages literally named
  `tests`. Under pytest's default `prepend` import mode only one of them can
  own the `tests` module name, so `pytest scripts/tests source/tests` in one
  invocation used to abort with 15 `ModuleNotFoundError: No module named
  'tests.<mod>'` collection errors. The root `pytest.ini` fixes this with
  `--import-mode=importlib` (module names derived from the rootdir-relative
  path, so the two packages no longer collide) plus
  `pythonpath = src scripts` (which replaces the sys.path entry that the
  `prepend` mode used to inject, keeping `import lib.…` / `import
  thinclient_build.…` working).
- Run both directories together: `.venv/bin/python3 -m pytest` (the ini's
  `testpaths` already names both) or explicitly
  `.venv/bin/python3 -m pytest source/tests scripts/tests -q`.
- Expected state, measured 2026-09-25 (file-by-file, one pytest process per
  file — the whole suite in one process peaks several GB and competes with
  whatever else runs on this 31 GB host): `source/tests` 568 passed, 0 failed,
  0 errors, 0 skipped; `scripts/tests` 229 passed, 0 failed, 0 errors;
  combined collection 797 tests, 0 errors. A non-zero failure count is a
  regression, not background noise. Sweep record: the 11 failures + 1
  collection error standing before 2026-09-25 were all stale tests — see
  `docs/CODE_INVARIANTS.md` §"source/tests — conventions & pinned invariants".
- `test_build_resume.py`, a standalone research driver that collected 0
  tests (needs `data/thinclient_index/spool_backup/`), moved 2026-10-11 to
  `scripts/archive/bmp_era/test_build_resume.py` with the BMP code path.

## scripts/tests/ (contract pins worth knowing)

- Payload contract: dense/ absence must be SAFE and the environment gate FREE;
  only the literal `"1"` enables gated legs (typos leave the default).
  Leg provenance is opt-in and must be ranking-neutral. Per-leg metrics
  are process-global — tests measure a window, not totals.
- test_meta_staging: re-copy lands on a new inode (same inode == the copy
  did not run); size-equality traps use same-field-width rows + forged
  mtimes.
- test_served_seismic_path: the served path must take the manifest+mmap
  branch — a Path-A stock deserialize appearing where a mmap RuntimeError
  is expected means a silent fallback regression.
- test_seismic_sequential: C2 flat layout is the only layout
  MmapSeismicIndex loads with non-None doc_mapping; the release-pages test
  detects a stale `.so` (no hook → no-op) so it can't pass as a tautology.
- test_serve_query_log: rotation keeps live + `.1` only; staging defaults
  on / explicit production defaults off; `log()` must never block (flood
  drops, not raises).
- test_snapshot_downloader_durability: pins buffer-before-checkpoint and
  the removal of the hardcoded 3-arg fallback (the mixed-schema bug).
- test_demo_payload_manifest: the never-ship list (dense leg, warm-cache
  runtime state, rollback-ladder shard variants) — `--include-dense` must
  not smuggle the dense leg in.

## scripts/archive/deploy_opensearch_era/

Moved 2026-10-11 from `deploy/` (CLOSED SUPERSEDED; record only, see its
README); `ntfy/` moved to `scripts/demo_broker/ntfy/` the same day.
`truenas_monitor/` and `do_offload/` below are local directories
(gitignored), not in the repository.

- **truenas_monitor/checks.sh**: dataset capacity is probed per-path
  explicitly — inside the container, bind mounts on one ZFS pool coalesce
  under a single unlabelled device line, so `df | grep` monitors nothing.
  "Bad" container = unhealthy OR not-running-but-not-Exited(0) — ignores
  init/permission sidecars (`ix-*-permissions`) that correctly exit 0
  once. Monitor's own RestartCount distinguishes a real crash-loop
  (climbing) from a fresh redeploy (0). A credit monitor that can't see is
  worse than useless: every failure mode is LOUD (`anom=1`), and
  `do_check_ok=1` is emitted only when the droplet read truly succeeded —
  `monitor_loop.sh` acts on droplet/spend state only in that case (a
  transient API blip must not wipe `seen_droplets` and re-fire "new
  droplet" for everything). curl writes the body to a temp file (`-o`)
  and status to stdout (`-w`) — in-string splitting once left a stray
  "200" that broke jq. Encoder freshness comes from the heartbeat EPOCH,
  not file mtime (rsync preserves mtime). Phase-2 host hooks (zpool/
  smartctl) are intentionally absent in Phase 1.
- **truenas_monitor/monitor_loop.sh + compose**: reactions are NOTIFY-ONLY
  unless `REACTIONS_ENABLED=true` AND an allowlist exists — the loop never
  stops/kills containers; do NOT flip without the allowlist. The socket
  proxy grants CONTAINERS/INFO read-only, POST=0 — the single line that
  makes the deployment safe. Spend alerts fire on first dollar from zero
  or a jump ≥ delta, rebasing quietly on a billing-month rollover;
  progress milestones persist in $STATE so a restart never re-fires and a
  rewound % rebases. `HEARTBEAT_S <= 0` disables heartbeats only. Policy
  files are bind-mounted read-only so the image stays generic.
- **demo_droplet**: deleted 2026-10-11 (never-run DigitalOcean boot stack
  for a SPLADE-on-Qdrant serve; DO and the Qdrant service are gone),
  kept in the restore tag `pre-codebase-triage-2026-10-11` (held by the owner).
- **mcp_http.supervisor.conf**: one long-lived server so the heavy models
  load once (the per-connect cold start made stdio appear to hang);
  bound to 127.0.0.1 — remote access is layered via reverse proxy, never
  by widening the bind.
- **ntfy** (`scripts/demo_broker/ntfy/`, live): `NTFY_BEHIND_PROXY=true` trusts X-Forwarded-* from NPM;
  deny-all + token is what makes public exposure safe; host port from the
  30200–30299 range convention.
- **do_offload** (encode-only offload; plan doc in `docs/deprecated/`):
  `SFU_DO_TAG=sfu-encode` — teardown.sh ONLY ever destroys this tag;
  `SFU_MAX_HOURS` (orchestrator destroys past this) + `SFU_DEADMAN_HOURS`
  (droplet self-shutdown if orchestrator dies) are the two-layer cost
  guardrail; `SFU_VOLUME_SIZE_GB=0` = no block volume (DO caps ~100 GB);
  GPU droplets are region-restricted (tor1/nyc2/atl1). NOTE 2026-09-01:
  the companion scripts (`provision_build.sh`, `teardown.sh`) do not exist
  in the directory — configuration for removed scripts.
- **deploy scripts**: build-new-image-before-stopping-old is the
  zero-downtime ordering; healthcheck.sh exit 0 = healthy, 1 = unhealthy
  (cron/CI contract).

## Mirrored knowledge from evidence harnesses (files NOT stripped)

`scripts/seismic_testbed/` + `scripts/experiments/` keep their comments
(pre-registered bars live in harness source at evidence commits — for example,
`j1_flat_sidecar_serving_ab.py` states the protocol: bars are committed
BEFORE any arm runs, so git history is the timestamp). Most-reusable items
mirrored here:

- **Zero-decode format model** (`c0_format_wall_summary_bench.py`): the
  on-disk model is little-endian, `MAGIC 0x5A45524F` ("ZERO"), header
  `<IIII` (n_terms/n_summaries/n_values), `SummaryPair {s_id: u32, value:
  u8, _pad: [u8;3]}` = 8 B naturally aligned; modeling upstream's
  compressed offsets/BitField as flat u32 is the BEST CASE for zero-decode
  (makes the negative result conservative). Upstream index files are
  bincode 2.x serde fixed-int LE (parser verified byte-exact in E1).
- **posting_lists.bin walk rule** (q6/q6b): the file may carry a
  sub-8-byte tail (last list's u8/u16 slices) — only read fully-in-bounds
  u64 words; a naive `view(uint64)` crashes.
- **dv visited starts are u64 WORD offsets into forward_data.bin** (×8 for
  bytes) — everything downstream is wrong by 8× if read as bytes. The Q12
  "1.6 GB→50%, 4.2 GB→80%" curve is a GLOBAL 8-shard coverage curve, NOT
  per-shard — per-shard budgets are the global budget split
  proportionally (each shard's touched set is only ~0.94 GB). F1 sidecar
  `version_keys` = {forward_format, forward_format_version,
  forward_reordered, forward_data_words}; a mismatch (for example, E8
  reconversion) must fail loud, not pin garbage. Budget aliases: 1.6 →
  hot50_1.6gb, 4.2 → hot80_4.2gb; the F3 dials keep `full` floor-pin
  semantics so re-runs reproduce the 2026-07-14 cells.
- **WSL2 measurement gotchas**: `echo 3 > drop_caches` fails on WSL2 even
  under sudo ("Read-only file system") — use
  `posix_fadvise(POSIX_FADV_DONTNEED)`, evicting BOTH arms' files so arm
  order can't leave one warmer. Host-run cells drop the shared page cache
  via a privileged throwaway container — without it the previous cell's
  residency leaks into pass 1 (cgroup charging is first-toucher); the app
  container has no docker daemon and read-only cgroups. Git Bash needs
  `MSYS_NO_PATHCONV=1`. `torch` import is the peak-RSS moment (transient
  ENOMEM mid-run on WSL2) — pay it first, before sampling allocations or
  the mmap load. Freshly-mmap'd pages report RssFile ≈ 0 until touched.
  `/proc/self/stat`: majflt is field 12 (1-indexed), field 10 of
  `/proc/<pid>/stat` in the wi7 form; comm must have no spaces for naive
  parsing.
- **bpftrace/tracing** (r3): only one BEGIN probe may exist (concatenating
  BEGIN-wrapped files fails; `--include` is C-preprocessor only — un-parsed
  bpftrace syntax → empty maps → predicate always false → ZERO events, the
  silent-failure class). Perf loss lines are "Lost N events" (capital L in
  0.17; parse case-insensitively). `cachestat` is syscall 451 on x86_64.
  The unprivileged app container has no debugfs/bpftrace/CAP_BPF —
  probes run in a throwaway privileged container, never installed into
  the app image. mincore returns one bit per page in the low bit of each
  byte; mmap requires nonzero length ≤ file size; numpy
  `__array_interface__["data"]` exposes a read-only buffer's pointer
  (ctypes `from_buffer` needs writable).
- **Serving constants register** (duplicated in harnesses deliberately):
  `RRF_K = 60`, `TOP_K = 50`, `SPLADE_QUERY_TERMS = 64`,
  k′ = max(2×top_k, 100) — the served default; do NOT set
  `SFU_SEISMIC_K_PRIME` in parity runs; query_cut unset = all terms.
  `SFU_SEISMIC_PREFLOOR`: 1 = Fix #4 footing (posting lists + doc
  mapping), 2 = also forward_offsets.bin. `SFU_MEMCOMPRESSION_REGIME` ∈
  {zram, zswap, windows_compression, disk_swap, off, unknown} — under
  zram/zswap "VmSwap > 0" is compressed RAM, not the disk-confound
  symptom.
- **Judged-eval hygiene**: LLM-judge caches are per-model and ISOLATED
  (Kimi runs must never touch the Haiku cache — bypass `judge_query()`'s
  cache when judging with another model). Judge cache keys are
  `query[:80]` — paraphrase sets must use the same truncation to inherit
  ground truth. Kimi is a reasoning model: `max_tokens` too low (512) is
  exhausted by hidden reasoning → content None (`finish_reason=length`);
  2048 leaves room. A reply naming only a stray id must not zero the
  other papers in the batch (majority-of-batch rule); an all-zero topic is
  an outage signature (incident 2026-08-18: 55 + 25 consecutive
  all-zero topics from service windows) — retry the topic once.
- **G2/G6 traps**: `MED_BIO_TOTAL_POSTINGS = 152,996,652` (2.0M docs ×
  76.5 nnz) — n_postings budgets above it saturate the global selection;
  a degenerate baseline returning 1–6 docs/query makes SEISMIC dominate
  RRF and overlap collapse to a false 1.0 (the comparison measures
  SEISMIC versus itself). F6 cells are refused when queries are swallowed
  no-ops (the invalid run scored 298–300/300 0-ms no-ops as PHENOMENAL).
  Commit pins: query-cut lever `d27bb3e`, encode/traverse split `efce80e`,
  G2 sweep-#1 negative result `bfe6628`.
- **`wslrh_convergence_ladder.py` (WSL2 re-host driver, added 2026-09-29;
  `spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` §6 gap 2; this
  file is comment-free by coordinator instruction, so its constraints live
  here)**: the L0 path is the judged `r2_convergence_ladder.py` verbatim
  (load, 40-query mix, convergence rule, per-pass record, exit 3 on empty
  results, VmSwap rule) — never change a shared key's meaning; new
  information is a new key. `--arm` is verified against
  `/sys/kernel/mm/lru_gen/enabled` and a mismatch exits 4 before the index
  is touched (N8). One lever per cell: `--postload-reclaim-bytes` (L3, the
  t23 `memory.reclaim` write verbatim) and `--f5-release-except SIDECAR`
  (F5) together exit 2. F5 keeps EXACTLY the extents
  `prefault_hotset()` prefaulted from that sidecar (same
  `budget_bytes_per_shard` clamp, same `_coalesce_extents`, imported from
  the backend so the two cannot drift); a missing / wrong-schema /
  version-mismatched sidecar exits 5 (an F5 cell without its map must not
  produce a plausible record). The F5 and L3 blocks share one key set
  (`requested_bytes`, `freed_bytes`, `write_status`, `pre_gauges`,
  `post_gauges`, `elapsed_s`, `rssfile_pre`/`rssfile_post` in BYTES,
  `hot_resident_pct_pre`/`_post`) so W7 compares them field-for-field;
  `freed_bytes` is the `memory.current` delta for both, `released_bytes` is
  the F5 hook's own return. `hot_resident_pct` is mincore(2) on a private
  read-only mapping of each shard's `forward_data.bin` (page-cache residency
  is per file; mincore never faults a page in), counted over the kept
  extents. F5 records `scope`: `all_slabs` only when the served `.so`
  exposes `release_pages_except_by_slab` (the 2026-08-31 scope fix);
  `forward_slab_only_prefix_hook` means the pre-fix `.so` answered and the
  cell reproduces the 2026-07-14 NULL scope, not the fixed one — the
  orchestrator quarantines such F5 cells. After either lever the cgroup /
  vmstat baselines are re-read so pass-1 deltas are query-only. `rehost`
  block per §9; `classification` never emits `timeout` (that is the
  orchestrator's shed). Pins: `scripts/tests/test_wslrh_convergence_ladder.py`
  (backend mocked; no index, no cgroup, no cell).
- **Miscellaneous**: the C1a converter binary builds via `cargo build --release
  --bin c1a_mmap_index` from `spike/seismic_upstream` (lives in gitignored
  target/); served mmap directories persist under `data/seismic_150m/index/plan01/`
  while G7 sources may stay on /tmp (regenerable from spool_backup);
  `scripts/seismic_testbed/seismic_backend.py`/`seismic_federated.py` are
  pure re-export shims — canonical:
  `source/lib/thinclient/sharded_seismic_backend.py`. Build-RAM safety factor
  1.3 covers allocator fragmentation + vocab map. WI-5 subset stats: the
  sections/ directory listing replaces a full 9p SQL scan; prefix samples are
  biased — never extrapolate as uniform.

### spike/dict_effect_at_scale/eval_dict_effect_at_scale.py (2026-10-19, CLOSED MEASURED)

- Timed IR spike, NOT product code: imports nothing from `source/`; the
  production constants (DICT_SIZE 112 KB, level 19, BLOCK_TARGET 32 KB,
  TRAIN_TARGET_DOCS 20,000, stamp file names) are copied, so a change to
  `abstracts.py` defaults must be mirrored by hand before a re-run.
- Reads the flat sidecar only (`blocks.bin` via `pread`, the three block
  arrays, `dicts.json`, `zdict_<name>`, `loc_b/off/n.npy`, `locator.json`);
  docs per block = `bincount(loc_b)`, valid only when `locator.json`
  `skipped_non_wid == 0`. Never writes under `data/thinclient_index/`.
- Parity `pass` means every block's recompression with its shipped dictionary
  is byte-identical to the stored bytes; that only holds with the zstd
  version the store was built with (1.5.7). A version drift reports
  `roundtrip_pass` separately and `pass: false` — do not quote arm a as "what
  is on disk" then.
- Arm d reuses arm a's bytes for latin blocks and for buckets without their
  own dictionary (mirrors the reader's latin fallback); arm c's dictionary is
  trained on a uniform random doc sample (seed 20261019), which differs from
  the writer's first-20k-in-ingest-order sample.
- Per-block row dtype caps: `docs` and `dec_us_*` are uint16 (decode µs
  capped at 65,535; the cap count is recorded per arm), `raw`/arm bytes
  uint32. Decode timings in the census are under full 16-thread compression
  load; the fair dictionary decode cost is the separate idle run
  (`_decode_idle.json`).
- Takes `/tmp/sfu_latency_measure.lock` (`O_EXCL`) for the census and removes
  it in `finally`; refuses to start if it exists. `--cold-scan-only` streams
  all nine packed archives (~17 min, single thread) into `<out>_cold_scan.json`
  and the census embeds that file if present; the two modes are meant to run
  concurrently.

## Names that look dead but are live — dead-code audit 2026-10-10

- `scripts/demo_broker/app.py`: `_startup`, `_shutdown`, `app_static`,
  `api_proxy`, `mcp_root`, `mcp_sub`, `admin_*`, `arch_search`,
  `architecture`, `landing`, `html_404` have no Python callers — FastAPI
  decorators register them. `tenants.Session` fields are positional
  constructor slots matching the `sessions` table columns. `test_dial.py`'s
  fake runner must accept `capture_output, text` (the `subprocess.run`
  signature `dial.py` uses). `LockedDB.row_factory`'s getter has no reader but
  the property setter is used by `TenantStore.__init__`. `app.py:314/403`
  annotate `Response` without importing it (ruff F821; annotations only).
- `spike/delta_ingest/`: `DocRecord` fields (incl. `updated_at`, `extra`) are
  JSON-serialised into ledger `records` rows and rebuilt with `cls(**d)` —
  removing or renaming any field breaks reading existing ledgers.
  `IngestProfile` fields (incl. the unenforced `flush_bytes`) are serialised
  via `as_dict()` into generation.json, `cli status` and eval result JSON.
  `oa_bitmap.open_partition` sets `r.raw.decode_content = False` (urllib3,
  write-only by design). `OpenAlexApiAdapter.cost_usd` is a write-only
  accumulator that 02_DESIGN documents. `ExactSparseBuffer` (buffer.py),
  `OpenAlexApiAdapter.probe_deleted` and the test-only `DocRecord.is_openalex`
  were removed 2026-10-11 (codebase triage; no callers; the serving-side
  exact scorer is `lib/thinclient/delta_layer._ExactSparse`).
  `oa_bitmap.pairs_from_adapter` is test-only but kept: it is what makes the
  O17 builder source-agnostic as OA_BITMAP_FINDINGS §2.1 claims.
