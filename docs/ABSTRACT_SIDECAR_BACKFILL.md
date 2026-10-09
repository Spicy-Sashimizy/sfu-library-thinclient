# Abstract sidecar backfill — cold sections from the offloaded snapshot

**Status:** DEFERRED 2026-08-18 (operator decision: the OpenAlex polite-pool live fetch is sufficient; design only, nothing built)

**Date:** 2026-08-18 · **Status: DESIGN ONLY, NOTHING BUILT — DEFERRED by
operator decision 2026-08-18: the OpenAlex polite-pool live-fetch is sufficient
for the demo's purposes.** This doc exists so the idea isn't re-derived from
scratch when (if) it's picked up.

## The gap

Only `social_sciences__recent` has a local abstract store (26.3M abstracts,
13 GB SQLite + 11 GB flat, gate-passed 2026-08-17). The other 9 sections have
**no abstract store at all** — a deliberate build-time space decision
(`builder.py`: `AbstractStoreWriter(...) if hot else None`; only that section
was built hot). Their abstracts are *searchable* (tantivy/SPLADE indexed
title+abstract for every section) but not *stored* for display/rerank.

At serve time `retriever.fetch_abstracts()` fills the gap from the OpenAlex
API: sidecars first, then batched GETs (≤50 ids per call,
`select=id,abstract_inverted_index`, **before** rerank) for the misses —
measured miss mix ~53% of ranked ids on federated queries. Cost of that path:
**$0 and 0 tokens** (OpenAlex is keyless; polite pool ~100k calls/day,
~10 req/s shared identity; a search is 1–2 calls, a single-item abstract click
is 1 call; the broker's per-session caps of 30/min / 500/day keep a busy demo
day around ~10³ calls). The real trade-offs are **latency** (~200–500 ms added
pre-rerank) and a **runtime dependency** (OpenAlex down ⇒ cold-section
abstracts degrade to title-only). LLM-context token cost is identical either
way — the abstract text enters the tool result regardless of source.

## The source data

The build spool no longer exists locally, but the filtered snapshot survives on
the TrueNAS server under **`Gordos_things`**: `works_part_NNNN.jsonl.gz`
chunks (gzip JSONL, 500,000 records/chunk, written by
`scripts/snapshot_downloader.py` with title/abstract retained). ~150M records,
~200–250 GB *(est.)*.

**Gzip is not seekable** — the chunks cannot serve per-request lookups as-is
(one abstract ⇒ decompress ~half a chunk, seconds per hit). Serving directly
*from* the NAS is also ruled out for a public demo: it chains the rerank path
to residential upload bandwidth and uptime — strictly worse than the OpenAlex
fallback it would replace. The NAS holds the *source*; any serving artifact
ships in the payload.

## The design — same format, lower level (minimal build)

The expensive part of the real sidecar build is the compression, not the
format: `abstracts.py` hardcodes `COMPRESSION_LEVEL = 19`, which is why the hot
section built at ~375 docs/s/worker vs ~1,050 non-hot (THIN_CLIENT_SWAP,
measured 2026-06-13). The per-script **dictionary training** — which carries
most of the ratio win on small records (ru −40% … zh −32% vs an English dict)
— is a cheap one-time 20k-doc sample per bucket and is level-independent.

1. **Make the level overridable** (writer arg or env; default stays 19 —
   nothing shipped changes).
2. **Abstracts-only backfill script** (new, small): stream the NAS chunks →
   classify each work into its section (`sections.py`) → append to that
   section's `AbstractStoreWriter` at level ~6. No tantivy/BMP/SPLADE/meta
   rebuild — the abstract store is a pure sidecar. The writer already supports
   WAL checkpoint/resume, so a mid-run kill loses nothing.
3. **Everything downstream already exists**: the v3 reader serves the store
   as-is; `fetch_abstracts` prefers sidecars over OpenAlex with zero code
   change; `build_flat_blocks.py` + its byte-parity gate can convert any
   section to flat later (optional — the 1.09× serving polish and −1.9 GB/
   section, deferrable; SQLite serves correctly on day one). Any section can
   also be *re*-compressed at 19 later without touching the reader — same
   container format.

## Estimates (all *est.*, nothing measured)

| Quantity | Estimate | Basis |
|---|---|---|
| Build wall-clock (SQLite stores, 9 sections) | **~2–4 h** | bottleneck becomes gzip-decode + JSON parse + NAS read, parallel over ~300 chunks / 16 cores; zstd-6+dict removes the level-19 penalty |
| + optional flat conversion + gates | ~2–4 h | scaling the measured single-section build |
| Payload growth (level ~6) | **+60–80 GB** | 26.3M abstracts → 11 GB flat at level 19; ~75–90M more abstracts; +15–30% for 19→6 |
| Payload growth (level 19, slow path) | +50–65 GB | same scaling, full 8–14 h build |
| Abstracts to write | ~75–90M | ~124M cold-section docs × OpenAlex abstract coverage — **coverage is the load-bearing unknown; measure it from one chunk before believing any row above** |

## Prerequisites when picked up

1. NAS reachable from the build container (mount or SSH/SMB into
   `Gordos_things`); verify **one chunk** first: records carry
   `abstract`/`abstract_inverted_index` for cold-section works, and measure
   per-section coverage.
2. Disk: ~250 GB streamed input (no local copy needed if mounted) + up to
   ~80 GB output; the container had 759 GB free on 2026-08-18.
3. Do it **before** the OCI Phase-1 payload seed if it's wanted for the demo —
   one transfer instead of two. It is additive (drop-in sidecar files), so it
   can also land after launch with no index rebuild.

## Decision record

- **2026-08-18 — DEFERRED.** Operator: the OpenAlex polite pool is enough for
  the demo's purposes. The live-fetch path stays the documented, accepted
  behavior (`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §8 gotcha); this doc is the pickup point
  if latency/offline-robustness ever justify the ~2–4 h build + ~70 GB payload.
