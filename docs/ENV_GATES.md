# SFU_* / DEMO_* env-gate reference (consolidated 2026-09-01)

Every serving/build gate, its default, and its parsing quirk, in one
grep-able place. The code is authoritative; this table is the index.
Details and provenance: `CODE_INVARIANTS.md`, `CODE_INVARIANTS_SCRIPTS.md`,
`THIN_CLIENT_SWAP.md`, `SEISMIC_ARCHIVE_SPLIT.md`.

## Parsing quirks (read first)

- **Literal-`1`-only gates**: `SFU_DENSE_LEG`, `SFU_ABSTRACTS_PREFAULT`,
  `SFU_CE_ONNX` — ONLY the literal string `1` enables; any other value
  (including typos) leaves the default OFF.
- **Tri-state**: `SFU_SEISMIC_MLOCK_FLOOR` — `1` = rescoped navigation
  floor (~20 MB/shard, 2026-08-17); `full` = the 2026-07-14 whole-slab pin
  (~13.4 GB, measurement reproduction only). `SFU_SEISMIC_PREFLOOR` — `1`
  = Fix #4 footing; `2` = also forward_offsets.bin.
- **Inverted staging defaults**: `SFU_SERVE_QUERY_LOG`, `SFU_RESULT_CACHE`,
  `SFU_CACHE_PRESEED` — unset ⇒ ON in staging; an explicit `production`
  profile is the only thing that defaults them OFF (prod must opt in).
- **Set-always-wins**: `SFU_SEISMIC_SHARD_MANIFEST` — a set value always
  overrides the promotion ladder (the one-env rollback); a set-but-missing
  path fails loudly.

## Serving backends & index

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SEARCH_BACKEND` | `thinclient` | `opensearch` restores the legacy backend (evals) |
| `SFU_SPLADE_BACKEND` | `seismic` (since 2026-07-06) | `qdrant` = one-env rollback (`SFU_SPLADE_QDRANT_URL`); `bmp` forensics only |
| `SFU_SEISMIC_SHARD_MANIFEST` | unset ⇒ promotion ladder (E8 dv-v2 → E5 dv-v1 → plain dv) | one-env rollback to any prior served shard set |
| `SFU_SEISMIC_FEDERATION` | unset ⇒ FS-aware (sequential on 9p/NFS, parallel on local disk) | `parallel` / `sequential`; env always overrides the heuristic |
| `SFU_SEISMIC_K_PRIME` | unset ⇒ max(2×top_k, 100) | do NOT set in parity runs — the default is the served behavior |
| `SFU_SEISMIC_QUERY_CUT` | unset = all terms (recall-first) | §C1 lever: 10 ⇒ 4× traverse at overlap 0.995 |
| `SFU_THINCLIENT_ORDINALS` | unset (OFF) | ordinal filter arrays dir; FAILS CLOSED if configured and unusable |
| `SFU_THINCLIENT_INDEX_ROOT` | `data/thinclient_index` | empty value silently targets the REAL serving root — beware in staging |
| `SFU_SKIP_BMP` | off | load tantivy/meta/dense only (BM25F leg on small hosts) |
| `SFU_LOAD_MEM_FLOOR_GB` | set | refuse a BMP load that would OOM (3.07× on-disk resident) |
| `SFU_DENSE_LEG` | **OFF since 2026-08-18** (ablation: harmful at 0.4% coverage) | literal `1` enables the whole leg (seed + warm cache) |
| `SFU_DENSE_WARMCACHE` | on when leg on | `0` disables the cache only; inert while the leg is off |

## Staging / residency levers (dev-container; production no-ops)

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SEISMIC_STAGE_DIR` | unset | copy shards off 9p/NFS to local disk (~160–240× fault speedup); no-op on a droplet |
| `SFU_META_STAGE_DIR` / `SFU_STAGE_META=1` | unset | stage meta.sqlite (55× filter-stage win on 9p); refuses on a local-FS source |
| `SFU_META_STAGE_FORCE=1` | off | stage even off a local FS (tests) |
| `SFU_META_STAGE_VERIFY` | `fingerprint` | `size` \| `fingerprint` (size + head/tail 64 KiB sha256) \| `sha256` |
| `SFU_ABSTRACTS_PREFAULT` | OFF (J1: costs load time; 0.919× cold-start regression otherwise absorbed) | literal `1` prefaults the 421 MB flat locator |

## Disk-streaming pin tier (all default OFF = byte-identical; kill-switch discipline)

| Gate | Meaning |
|---|---|
| `SFU_SEISMIC_MLOCK_FLOOR` | `1` navigation floor / `full` whole-slab reproduction |
| `SFU_SEISMIC_MLOCK_FLOOR_MB` | floor budget, default 160 MB total |
| `SFU_SEISMIC_PIN_BUDGET_GB` | F3 hot-set pin budget (aliases: 1.6→hot50, 4.2→hot80) |
| `SFU_SEISMIC_PREFLOOR_HOTSET` | F6 prefault-at-load (reclaimable, not locked); budget = PIN_BUDGET_GB or 1.6 GB |
| `SFU_SEISMIC_PREFLOOR` | 1 = Fix #4 floor; 2 = + forward_offsets.bin |

## Serve app (HTTP)

| Gate | Default | Meaning |
|---|---|---|
| `SFU_HTTP_WARMUP` | on | `0` disables the startup warmup battery (then `warm` reports true immediately) |
| `SFU_RESULT_CACHE` | staging-on | WI-17 read-through cache; `0` = the one-env rollback. Tunables: `_TTL` (s), `_MAX_SIZE`, `_MAX_MEM_MB` |
| `SFU_CACHE_PRESEED` | on (no-op when cache off) | WI-17b post-warmup primer |
| `SFU_SEARCH_SPECULATE` | **OFF** (owner flips defaults, not builds) | WI-18 keystroke speculation; `SFU_SPECULATE_MIN_RATIO` (0.35), `SFU_SPECULATE_LITERAL` (OFF) |
| `SFU_SERVE_QUERY_LOG` | staging-on | WI-2 query log; `_RAW=1` captures raw text (OFF: hash-only), `_MAX_BYTES` rotation |
| `SFU_SEQUENTIAL_MODE` | absent | set by the Windows START.bat; advertises on /health so the GUI queues searches |
| `SFU_DEMO_UPDATE_VERIFY_SEISMIC` | — | `/verify` forces the lazy seismic load (WI-13 update gate) |

## Models

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SPLADE_MODEL_PATH` | bert-FUSED local export (D2, 2026-07-09) | bare HF hub ids don't work air-gapped |
| `SFU_EMBEDDING_MODEL_PATH` | repo-relative v5 | must match LambdaMART training checkpoint (parity) |
| `SFU_CE_MODEL_PATH` | v1 (base-flip DECISION PENDING; base measured +0.0165 better 2026-08-19) | torch CE checkpoint |
| `SFU_CE_ONNX` | OFF | literal `1`: int8 ONNX CE — slower at serve shape (52 vs 11.8 ms batch-20); single-stream fallback only |
| `SFU_ORT_INTRA_THREADS` | small | keep tiny/non-spinning with the TRT EP (full-width pool starved the GPU 3.5k→960 docs/s) |
| `SFU_SEISMIC_M2_INT6` | OFF | M2 integer-dot kernel (NOT promoted — gate a failed at n=100) |

## Demo broker (DEMO_*)

| Gate | Default | Meaning |
|---|---|---|
| `DEMO_BROKER_LIVE` | `0` | **the dry-run/spend gate** |
| `DEMO_CLOUD` | `do` | `oci` = the live OCI deploy |
| `OCI_STOP_ACTION` | SOFTSTOP | ACPI shutdown; `STOP` = hard power-off fallback |
| `DEMO_WATCHDOG_HEARTBEAT_HOUR` / `_FAIL_THRESHOLD` / `_STATE_PATH` | `9` / `2` / `watchdog.json` | `watchdog.py` (systemd timer, read-only): ntfy on instance-state change, health failures, recovery, daily heartbeat. Live since 2026-09-07 |
| `DEMO_PIN_RUNNING` | `0` | `1` = `_destroy` is a no-op (reaper + killswitch log `reap_suppressed`, never stop). Live since 2026-09-07 (trial grace period, E5 limit 0) |
| `OCI_INSTANCE_IP` | set | private-IP proxy path, no control-plane call per request |
| `DEMO_MCP_RESERVED_SLOTS` | 2 | MCP-priority slots of the 6 global billable slots |
| `DEMO_DIAL_BACKEND` | off | `systemd` / `cgroup`; off ⇒ /admin/dial 404s |
| WI-9/10/11 gates | all OFF | leg breaker / shard isolation / overload shed — byte-identical when off |

## Ingest / eval

| Gate | Meaning |
|---|---|
| `SFU_MEMCOMPRESSION_REGIME` | operator assertion ∈ {zram, zswap, windows_compression, disk_swap, off, unknown} — changes the G8 latency-caveat verdict |
| `SFU_FEATURE_RRF_ENABLED` etc. | feature flags in `lib/config.py`; measured provenance in `BENCHMARK_METHODOLOGY.md` |
| `GUITB_HOST` | gui_testbed static server bind; default loopback-only |
