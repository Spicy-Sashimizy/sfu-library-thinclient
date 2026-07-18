# Artifact contract — oracle repo ⇄ portable client

**Pinned versions (bump explicitly, in this file, with a dated commit):**

| Pin | Value | Set |
|---|---|---|
| Bundle-manifest schema | WI-14 v1 (`portable_bundle_updater.py manifest`, 2026-07-17) | 2026-07-17 |
| Fixture set | `fixtures/topk_goldens_2026-07-17/` (WI-4 n=100 topk, shards 1+2, native+v3) | 2026-07-17 |
| Shard format | dv `e5.v2.mmap` (dotvbyte + E5 reorder + dv-v2 scale) | 2026-07-17 |
| Encoder | SPLADE ONNX fused (`models/splade_onnx_fused`, ORT-fusion PROMOTED 2026-07-09) | 2026-07-17 |

## What the oracle provides (immutable, versioned)

1. **Bundle manifest** — per-artifact `{path, sha256|pointer, bytes,
   version}`; shard-granular; pointer-mode for GB-scale mmap dirs.
2. **Golden fixtures** — per (shard, query) expected top-10 `(id, score)`
   pairs, produced by the served Python+native path. Bit-exact contract.
3. **Artifacts** — shards, models, `.so` build recipes. Never committed to
   either repo; fetched to gitignored paths.
4. **Specs** — GUI bare-bones/progress spec, reliability layer map,
   shipping decision doc (copied into `upstream_specs/` at import time,
   with their dates, so this repo builds against a frozen snapshot).

## What the client owes back

- A parity report per release (`parity_report_<date>.json`: fixture set
  date, targets tested, per-shard verdict) — copied back to the oracle's
  `data/eval_results/` so the research side knows what the client ships.
- Issues found in artifacts (bad checksum, manifest gap) filed as dated
  notes in the oracle's host queue file format.

## Drift rule

Any oracle-side change to shard format, encoder, or manifest schema =
new fixture set + new pin here BEFORE the client consumes it. A client
that gates green against pinned fixtures but stale pins is NOT releasable —
check pins against `sfu-library-thinclient` git log at release time.
